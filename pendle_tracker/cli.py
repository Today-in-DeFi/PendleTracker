#!/usr/bin/env python3
"""Command line interface for Pendle PT tracker."""

import sys
import time
import json
import signal
from pathlib import Path
from typing import List, Dict

import click
from .config import config
from .tracker import PTTracker
from .display import DisplayManager

# Google Sheets import (optional)
try:
    from .sheets_exporter import GoogleSheetsExporter
    SHEETS_AVAILABLE = True
except ImportError:
    SHEETS_AVAILABLE = False


@click.command()
@click.option('-c', '--config', 'config_file', help='Path to configuration file')
@click.option('-p', '--pt', help='PT market address to track')
@click.option('--chain-id', default=1, help='Chain ID (default: 1)')
@click.option('-s', '--search', help='Search for PT markets by symbol')
@click.option('-f', '--format', 'output_format', default='table',
              type=click.Choice(['table', 'json', 'csv', 'compact']),
              help='Output format')
@click.option('-h', '--history', is_flag=True, help='Include historical data')
@click.option('--history-days', default=7, help='Days of historical data')
@click.option('-w', '--watch', is_flag=True, help='Watch mode - continuous monitoring')
@click.option('--watch-interval', default=300, help='Watch interval in seconds')
@click.option('--export', help='Export data to file')
@click.option('--export-sheets', is_flag=True, help='Export data to Google Sheets')
@click.option('--sheet-id', help='Google Sheets ID to export to')
@click.option('--sheet-name', help='Google Sheets name to export to')
@click.option('--alert-threshold', type=float, help='APY alert threshold percentage')
@click.option('--no-colors', is_flag=True, help='Disable colored output')
@click.option('-q', '--quiet', is_flag=True, help='Minimal output')
@click.option('-v', '--verbose', is_flag=True, help='Verbose output')
@click.version_option(version='1.0.0')
def main(config_file, pt, chain_id, search, output_format, history, history_days,
         watch, watch_interval, export, export_sheets, sheet_id, sheet_name,
         alert_threshold, no_colors, quiet, verbose):
    """Track Pendle PT APYs and market data."""

    display = DisplayManager()
    tracker = None

    def cleanup(signum=None, frame=None):
        """Cleanup function for graceful shutdown."""
        if tracker:
            tracker.close()
        if not quiet:
            display.display_info("Goodbye!")
        sys.exit(0)

    # Register signal handlers
    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    try:
        # Configure colors
        if no_colors:
            config.set_cli_args({'enable_colors': False})

        # Load configuration file if specified
        if config_file:
            if not Path(config_file).exists():
                display.display_error(f"Configuration file not found: {config_file}")
                sys.exit(1)
            config.load_config_file(config_file)

        # Set CLI arguments in config
        cli_args = {
            'pt': pt,
            'chain_id': chain_id,
            'search': search,
            'format': output_format,
            'history': history,
            'history_days': history_days,
            'watch': watch,
            'watch_interval': watch_interval,
            'export': export,
            'export_sheets': export_sheets,
            'sheet_id': sheet_id,
            'sheet_name': sheet_name,
            'alert_threshold': alert_threshold,
            'quiet': quiet,
            'verbose': verbose
        }
        config.set_cli_args({k: v for k, v in cli_args.items() if v is not None})

        if not quiet:
            display.display_welcome()

        # Initialize tracker
        tracker = PTTracker()

        # Determine what to track
        pt_results = []

        if search:
            # Search mode
            pt_results = tracker.search_and_track(search, chain_id)
        elif pt:
            # Single PT mode
            result = tracker.track_pt(pt, chain_id)
            if result:
                pt_results = [result]
        else:
            # Config file mode
            pt_configs = config.get_pts()
            if not pt_configs:
                display.display_error(
                    'No PTs configured. Use --pt <address>, --search <query>, or provide a config file.'
                )
                display_usage_examples()
                sys.exit(1)
            pt_results = tracker.track_multiple_pts(pt_configs)

        if not pt_results:
            display.display_warning('No PT data retrieved')
            sys.exit(0)

        # Check for alerts
        alert_config = config.get_alert_config()
        for pt_data in pt_results:
            pt_data['alerts'] = tracker.check_alerts(pt_data, alert_config)

        # Display results
        if watch:
            run_watch_mode(tracker, pt_results, cli_args, display)
        else:
            display.display_pt_data(pt_results, output_format)

            # Export if requested
            if export:
                export_data(pt_results, export, output_format, display)

            # Export to sheets if requested
            if export_sheets or should_auto_export_sheets(cli_args):
                export_to_sheets(pt_results, cli_args, display)

    except Exception as e:
        display.display_error(str(e))
        if verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)
    finally:
        cleanup()


def run_watch_mode(tracker: PTTracker, initial_results: List[Dict], cli_args: Dict, display: DisplayManager):
    """Run continuous monitoring mode."""
    display.display_info(f"Starting watch mode (interval: {cli_args['watch_interval']}s)")
    display.display_info("Press Ctrl+C to stop\n")

    iteration = 0

    def update():
        nonlocal iteration
        try:
            iteration += 1

            if not cli_args.get('quiet'):
                # Clear screen
                click.clear()
                display.display_welcome()
                display.display_info(f"Update #{iteration} - {time.strftime('%H:%M:%S')}")

            # Re-fetch data
            pt_results = []

            if cli_args.get('search'):
                pt_results = tracker.search_and_track(cli_args['search'], cli_args['chain_id'])
            elif cli_args.get('pt'):
                result = tracker.track_pt(cli_args['pt'], cli_args['chain_id'])
                if result:
                    pt_results = [result]
            else:
                pt_configs = config.get_pts()
                pt_results = tracker.track_multiple_pts(pt_configs)

            # Check alerts
            alert_config = config.get_alert_config()
            for pt_data in pt_results:
                pt_data['alerts'] = tracker.check_alerts(pt_data, alert_config)

            # Display
            display.display_pt_data(pt_results, cli_args.get('format', 'table'))

            # Show any alerts prominently
            all_alerts = []
            for pt_data in pt_results:
                all_alerts.extend(pt_data.get('alerts', []))

            if all_alerts:
                display.console.print("\n[bold red]🚨 ACTIVE ALERTS:[/bold red]")
                for alert in all_alerts:
                    display.console.print(f"  {alert}")

            if not cli_args.get('quiet'):
                display.display_info(f"Next update in {cli_args['watch_interval']}s...")

        except Exception as e:
            display.display_error(f"Watch update failed: {e}")

    # Initial display
    update()

    # Watch loop
    try:
        while True:
            time.sleep(cli_args['watch_interval'])
            update()
    except KeyboardInterrupt:
        display.display_info("\nWatch mode stopped")


def export_data(pt_results: List[Dict], filename: str, format_type: str, display: DisplayManager):
    """Export data to file."""
    try:
        # Determine file extension and format
        if '.' not in filename:
            if format_type == 'csv':
                filename += '.csv'
            else:
                filename += '.json'

        # Prepare data
        if format_type == 'csv' or filename.endswith('.csv'):
            import csv
            from io import StringIO

            output = StringIO()
            headers = [
                'Symbol', 'Market_Address', 'Implied_APY', 'Underlying_APY', 'LP_APY',
                'Total_Liquidity', 'Volume_24h', 'Time_to_Expiry', 'Timestamp'
            ]

            writer = csv.writer(output)
            writer.writerow(headers)

            for pt in pt_results:
                row = [
                    pt['pt_info']['symbol'],
                    pt['market_address'],
                    pt['apy_data']['implied_apy'].replace('%', ''),
                    pt['apy_data']['underlying_apy'].replace('%', ''),
                    pt['apy_data']['lp_apy'].replace('%', ''),
                    pt['market_metrics']['total_liquidity'].replace('$', '').replace(',', ''),
                    pt['market_metrics']['volume_24h'].replace('$', '').replace(',', ''),
                    pt['pt_info']['time_to_expiry'] or '',
                    pt['timestamp']
                ]
                writer.writerow(row)

            data = output.getvalue()
        else:
            # JSON format
            data = json.dumps(pt_results, indent=2, default=str)

        # Write to file
        with open(filename, 'w') as f:
            f.write(data)

        display.display_success(f"Data exported to {filename}")

    except Exception as e:
        display.display_error(f"Export failed: {e}")


def should_auto_export_sheets(cli_args: Dict) -> bool:
    """Check if we should auto-export to sheets (when credentials exist)."""
    if cli_args.get('export_sheets'):
        return False  # Explicit flag takes precedence

    # Auto-export if credentials file exists and no explicit export flag
    credentials_file = config.get('google_credentials_file')
    return credentials_file and Path(credentials_file).exists()


def export_to_sheets(pt_results: List[Dict], cli_args: Dict, display: DisplayManager):
    """Export PT data to Google Sheets."""
    if not SHEETS_AVAILABLE:
        display.display_error(
            "Google Sheets dependencies not available. "
            "Install with: pip install gspread gspread-dataframe google-auth pandas"
        )
        if cli_args.get('export_sheets'):
            sys.exit(1)
        return

    try:
        exporter = GoogleSheetsExporter()

        # Get sheet parameters
        sheet_id = cli_args.get('sheet_id') or config.get('google_sheet_id')
        sheet_name = cli_args.get('sheet_name') or config.get('google_sheet_name')

        # Show service account email for sharing
        email = exporter.get_service_account_email()
        if email and not cli_args.get('quiet'):
            display.display_info(f"📧 Service account: {email}")
            display.display_info("   Make sure to share your Google Sheet with this email")

        # Export data
        exporter.export_to_sheets(
            pt_results,
            spreadsheet_id=sheet_id,
            spreadsheet_name=sheet_name,
            append_data=True
        )

    except Exception as e:
        display.display_error(f"Google Sheets export failed: {e}")
        if cli_args.get('export_sheets'):  # Only exit if explicitly requested
            sys.exit(1)
        else:
            display.display_warning("Auto-export disabled due to error")


def display_usage_examples():
    """Display usage examples."""
    examples = [
        "pendle-tracker --pt 0x1234...  # Track specific PT",
        "pendle-tracker --search \"stETH\"  # Search for stETH PTs",
        "pendle-tracker --config pts.json  # Use config file",
        "pendle-tracker --pt 0x1234... --watch  # Continuous monitoring",
        "pendle-tracker --pt 0x1234... --export data.json  # Export to file",
        "pendle-tracker --pt 0x1234... --export-sheets  # Export to Google Sheets",
        "pendle-tracker --pt 0x1234... --sheet-id 1dCaUh0gh3xcGIJAt9dO4EISXyw-ys_Td2SUbDsmcrtQ  # Specific sheet"
    ]

    print("\nUsage Examples:")
    for example in examples:
        print(f"  {example}")


if __name__ == '__main__':
    main()