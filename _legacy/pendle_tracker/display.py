"""Display and formatting utilities."""

import json
import csv
from io import StringIO
from typing import List, Dict, Any
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich import box
from tabulate import tabulate
from .config import config


class DisplayManager:
    """Handles data display and formatting."""

    def __init__(self):
        self.console = Console()
        self.enable_colors = config.get('enable_colors', True)

    def display_pt_data(self, pt_results: List[Dict], format_type: str = 'table'):
        """Display PT data in specified format."""
        if not pt_results:
            self.console.print("[yellow]No PT data to display[/yellow]")
            return

        format_type = format_type.lower()

        if format_type == 'json':
            self.display_json(pt_results)
        elif format_type == 'csv':
            self.display_csv(pt_results)
        elif format_type == 'compact':
            self.display_compact(pt_results)
        else:
            self.display_table(pt_results)

    def display_table(self, pt_results: List[Dict]):
        """Display data in rich table format."""
        # Main summary table
        table = Table(title="📊 Pendle PT APY Tracker", box=box.ROUNDED)

        table.add_column("PT Symbol", style="cyan", no_wrap=True)
        table.add_column("Implied APY", style="green", justify="right")
        table.add_column("Underlying APY", style="blue", justify="right")
        table.add_column("LP APY", style="magenta", justify="right")
        table.add_column("Liquidity", style="yellow", justify="right")
        table.add_column("24h Volume", style="white", justify="right")
        table.add_column("Time to Expiry", style="dim", justify="center")

        for pt in pt_results:
            table.add_row(
                pt['pt_info']['symbol'],
                self._format_apy_with_color(pt['apy_data']['implied_apy']),
                self._format_apy_with_color(pt['apy_data']['underlying_apy']),
                self._format_apy_with_color(pt['apy_data']['lp_apy']),
                pt['market_metrics']['total_liquidity'],
                pt['market_metrics']['volume_24h'],
                pt['pt_info']['time_to_expiry'] or 'N/A'
            )

        self.console.print(table)
        self.console.print()

        # Display detailed info for each PT
        for i, pt in enumerate(pt_results):
            if i > 0:
                self.console.print()
            self._display_detailed_pt_info(pt)

    def _display_detailed_pt_info(self, pt: Dict):
        """Display detailed information for a single PT."""
        # Header
        title = f"🎯 {pt['pt_info']['name']}"
        panel_content = []

        # Basic info
        panel_content.append(f"[cyan]Market Address:[/cyan] {pt['market_address']}")
        panel_content.append(f"[cyan]Symbol:[/cyan] {pt['pt_info']['symbol']}")

        if pt['pt_info']['expiry']:
            expiry_date = pt['pt_info']['expiry'][:10]  # Just the date part
            panel_content.append(f"[cyan]Expiry:[/cyan] {expiry_date} ({pt['pt_info']['time_to_expiry']})")

        # APY breakdown
        panel_content.append("")
        panel_content.append("[bold]📈 APY Breakdown:[/bold]")
        panel_content.append(f"  Implied APY:    {self._format_apy_with_color(pt['apy_data']['implied_apy'])}")
        panel_content.append(f"  Underlying APY: {self._format_apy_with_color(pt['apy_data']['underlying_apy'])}")
        panel_content.append(f"  LP APY:         {self._format_apy_with_color(pt['apy_data']['lp_apy'])}")

        if pt['apy_data']['swap_fee_apy'] != 'N/A':
            panel_content.append(f"  Swap Fee APY:   {self._format_apy_with_color(pt['apy_data']['swap_fee_apy'])}")

        # Market metrics
        panel_content.append("")
        panel_content.append("[bold]💰 Market Metrics:[/bold]")
        panel_content.append(f"  Total Liquidity:  [yellow]{pt['market_metrics']['total_liquidity']}[/yellow]")
        panel_content.append(f"  24h Volume:       {pt['market_metrics']['volume_24h']}")

        if pt['market_metrics']['total_volume'] != 'N/A':
            panel_content.append(f"  Total Volume:     [dim]{pt['market_metrics']['total_volume']}[/dim]")

        # Historical data
        if pt.get('historical'):
            self._add_historical_to_panel(panel_content, pt['historical'])

        # Alerts
        if pt.get('alerts'):
            panel_content.append("")
            panel_content.append("[bold red]🚨 Alerts:[/bold red]")
            for alert in pt['alerts']:
                panel_content.append(f"  {alert}")

        # Create and display panel
        panel = Panel(
            "\n".join(panel_content),
            title=title,
            border_style="blue"
        )
        self.console.print(panel)

    def _add_historical_to_panel(self, panel_content: List[str], historical: Dict):
        """Add historical data to panel content."""
        panel_content.append("")
        panel_content.append("[bold]📊 Historical Trends:[/bold]")

        trends = historical.get('trends', {})

        for trend_name, trend_data in trends.items():
            if trend_data and trend_data.get('change') != 'N/A':
                display_name = trend_name.replace('_', ' ').title()
                direction = trend_data['direction']
                change = trend_data['change']
                status = trend_data['status']

                color = 'green' if status == 'increasing' else 'red' if status == 'decreasing' else 'white'
                panel_content.append(f"  {display_name}: {direction} [{color}]{change}[/{color}] ({status})")

        if historical.get('stats'):
            panel_content.append("")
            panel_content.append("[bold]📈 APY Statistics:[/bold]")
            stats = historical['stats']
            panel_content.append(f"  Max: {self._format_apy_with_color(stats.get('max_implied_apy', 'N/A'))}")
            panel_content.append(f"  Min: {self._format_apy_with_color(stats.get('min_implied_apy', 'N/A'))}")
            panel_content.append(f"  Avg: {self._format_apy_with_color(stats.get('avg_implied_apy', 'N/A'))}")

    def display_compact(self, pt_results: List[Dict]):
        """Display data in compact format."""
        self.console.print("[bold]📊 PT APY Summary[/bold]")
        self.console.print("=" * 50)

        for pt in pt_results:
            symbol = pt['pt_info']['symbol'].ljust(12)
            apy = self._strip_markup(self._format_apy_with_color(pt['apy_data']['implied_apy'])).ljust(8)
            liquidity = pt['market_metrics']['total_liquidity'].ljust(10)

            line = f"{symbol} {apy} [yellow]{liquidity}[/yellow]"
            self.console.print(line)

    def display_json(self, pt_results: List[Dict]):
        """Display data as JSON."""
        print(json.dumps(pt_results, indent=2, default=str))

    def display_csv(self, pt_results: List[Dict]):
        """Display data as CSV."""
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

        print(output.getvalue())

    def _format_apy_with_color(self, apy_string: str) -> str:
        """Format APY string with appropriate color."""
        if not self.enable_colors:
            return apy_string

        if apy_string == 'N/A':
            return '[dim]N/A[/dim]'

        try:
            apy_value = float(apy_string.replace('%', ''))

            if apy_value >= 20:
                return f'[bold green]{apy_string}[/bold green]'
            elif apy_value >= 10:
                return f'[yellow]{apy_string}[/yellow]'
            elif apy_value >= 5:
                return f'[white]{apy_string}[/white]'
            else:
                return f'[red]{apy_string}[/red]'
        except ValueError:
            return f'[dim]{apy_string}[/dim]'

    def _strip_markup(self, rich_text: str) -> str:
        """Strip rich markup from text."""
        import re
        return re.sub(r'\[.*?\]', '', rich_text)

    def display_error(self, message: str):
        """Display error message."""
        self.console.print(f"[bold red]❌ Error: {message}[/bold red]")

    def display_warning(self, message: str):
        """Display warning message."""
        self.console.print(f"[bold yellow]⚠️  Warning: {message}[/bold yellow]")

    def display_success(self, message: str):
        """Display success message."""
        self.console.print(f"[bold green]✅ {message}[/bold green]")

    def display_info(self, message: str):
        """Display info message."""
        self.console.print(f"[bold blue]ℹ️  {message}[/bold blue]")

    def display_welcome(self):
        """Display welcome message."""
        welcome_panel = Panel(
            "[bold]🔥 Pendle PT APY Tracker[/bold]\n"
            "[dim]Track Principal Token yields and market data[/dim]",
            border_style="cyan",
            padding=(1, 2)
        )
        self.console.print(welcome_panel)