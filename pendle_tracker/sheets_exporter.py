"""Google Sheets export functionality for Pendle PT tracker."""

import os
import json
from typing import Dict, List, Optional
from datetime import datetime

# Google Sheets imports (optional)
try:
    import gspread
    from google.auth import default
    from google.oauth2 import service_account
    from gspread_dataframe import set_with_dataframe
    import pandas as pd
    SHEETS_AVAILABLE = True
except ImportError:
    SHEETS_AVAILABLE = False

from .config import config


class GoogleSheetsExporter:
    """Handle Google Sheets export functionality for Pendle PT data."""

    def __init__(self, credentials_file: Optional[str] = None):
        if not SHEETS_AVAILABLE:
            raise ImportError(
                "Google Sheets dependencies not available. "
                "Install with: pip install gspread gspread-dataframe google-auth pandas"
            )

        self.credentials_file = credentials_file or config.get('google_credentials_file')
        self.client = None

    def get_client(self) -> 'gspread.Client':
        """Get authenticated Google Sheets client."""
        if self.client:
            return self.client

        try:
            if self.credentials_file and os.path.exists(self.credentials_file):
                # Use service account
                print(f"🔐 Authenticating with service account: {self.credentials_file}")
                credentials = service_account.Credentials.from_service_account_file(
                    self.credentials_file,
                    scopes=[
                        'https://spreadsheets.google.com/feeds',
                        'https://www.googleapis.com/auth/drive'
                    ]
                )
                self.client = gspread.authorize(credentials)

                # Show service account email for sharing
                with open(self.credentials_file, 'r') as f:
                    creds_info = json.load(f)
                    email = creds_info.get('client_email', 'Unknown')
                    print(f"📧 Service account email: {email}")
                    print("   Share your Google Sheet with this email address")
            else:
                # Use default credentials
                print("🔐 Using default Google credentials")
                creds, project = default(scopes=[
                    'https://spreadsheets.google.com/feeds',
                    'https://www.googleapis.com/auth/drive'
                ])
                self.client = gspread.authorize(creds)

            return self.client

        except Exception as e:
            raise Exception(f"Google Sheets authentication failed: {e}")

    def get_or_create_worksheet(self, spreadsheet: 'gspread.Spreadsheet',
                              sheet_name: str) -> 'gspread.Worksheet':
        """Get existing worksheet or create new one with headers."""
        try:
            worksheet = spreadsheet.worksheet(sheet_name)
            print(f"✅ Found existing sheet: {sheet_name}")
            return worksheet
        except gspread.exceptions.WorksheetNotFound:
            print(f"📝 Creating new sheet: {sheet_name}")
            worksheet = spreadsheet.add_worksheet(title=sheet_name, rows=1000, cols=15)

            headers = [
                'Date', 'Time', 'PT Name', 'Expiry Date', 'Time to Expiry',
                'Implied APY (%)', 'Underlying APY (%)', 'LP APY (%)', 'Swap Fee APY (%)',
                'Total Liquidity (USD)', '24h Volume (USD)', 'Market Address'
            ]
            worksheet.update(values=[headers], range_name='A1:M1')
            print(f"📋 Added headers to new sheet")

            return worksheet

    def format_data_for_sheets(self, pt_data_list: List[Dict]) -> pd.DataFrame:
        """Convert PT data to DataFrame format for Google Sheets."""
        now = datetime.now()
        date_str = now.strftime('%Y-%m-%d')
        time_str = now.strftime('%H:%M:%S')

        rows = []
        for pt in pt_data_list:
            # Clean percentage values (remove % sign)
            implied_apy = pt['apy_data']['implied_apy'].replace('%', '') if pt['apy_data']['implied_apy'] != 'N/A' else ''
            underlying_apy = pt['apy_data']['underlying_apy'].replace('%', '') if pt['apy_data']['underlying_apy'] != 'N/A' else ''
            lp_apy = pt['apy_data']['lp_apy'].replace('%', '') if pt['apy_data']['lp_apy'] != 'N/A' else ''
            swap_fee_apy = pt['apy_data']['swap_fee_apy'].replace('%', '') if pt['apy_data']['swap_fee_apy'] != 'N/A' else ''

            # Clean currency values (remove $ and commas)
            liquidity = pt['market_metrics']['total_liquidity'].replace('$', '').replace(',', '') if pt['market_metrics']['total_liquidity'] != 'N/A' else ''
            volume_24h = pt['market_metrics']['volume_24h'].replace('$', '').replace(',', '') if pt['market_metrics']['volume_24h'] != 'N/A' else ''

            # Format expiry date
            expiry_date = ''
            if pt['pt_info']['expiry']:
                try:
                    expiry_date = datetime.fromisoformat(pt['pt_info']['expiry'].replace('Z', '+00:00')).strftime('%Y-%m-%d')
                except:
                    expiry_date = pt['pt_info']['expiry'][:10] if len(pt['pt_info']['expiry']) >= 10 else ''

            rows.append([
                date_str,
                time_str,
                pt['pt_info']['name'],
                expiry_date,
                pt['pt_info']['time_to_expiry'] or '',
                implied_apy,
                underlying_apy,
                lp_apy,
                swap_fee_apy,
                liquidity,
                volume_24h,
                pt['market_address']
            ])

        columns = [
            'Date', 'Time', 'PT Name', 'Expiry Date', 'Time to Expiry',
            'Implied APY (%)', 'Underlying APY (%)', 'LP APY (%)', 'Swap Fee APY (%)',
            'Total Liquidity (USD)', '24h Volume (USD)', 'Market Address'
        ]

        return pd.DataFrame(rows, columns=columns)

    def export_to_sheets(self, pt_data_list: List[Dict],
                        spreadsheet_id: Optional[str] = None,
                        spreadsheet_name: Optional[str] = None,
                        append_data: bool = True) -> None:
        """Export PT data to Google Sheets."""
        if not pt_data_list:
            print("❌ No PT data to export")
            return

        client = self.get_client()

        # Get spreadsheet
        try:
            if spreadsheet_id:
                spreadsheet = client.open_by_key(spreadsheet_id)
            elif spreadsheet_name:
                spreadsheet = client.open(spreadsheet_name)
            else:
                spreadsheet_name = "Pendle PT Tracker"
                try:
                    spreadsheet = client.open(spreadsheet_name)
                except gspread.exceptions.SpreadsheetNotFound:
                    print(f"📝 Creating new spreadsheet: {spreadsheet_name}")
                    spreadsheet = client.create(spreadsheet_name)
                    print(f"🔗 Spreadsheet URL: https://docs.google.com/spreadsheets/d/{spreadsheet.id}")

            print(f"📊 Using spreadsheet: {spreadsheet.title}")
        except Exception as e:
            print(f"❌ Error accessing spreadsheet: {e}")
            if hasattr(e, 'response'):
                print(f"Response status: {e.response.status_code}")
                print(f"Response text: {e.response.text}")
            return

        # Group PTs by chain and asset type for different worksheets
        pts_by_asset = {}
        for pt in pt_data_list:
            chain_id = pt.get('config', {}).get('chain_id', 1)
            chain_name = "Ethereum" if chain_id == 1 else f"Chain-{chain_id}"

            # Get asset name from PT name
            asset_name = pt['pt_info']['name']
            if asset_name == 'Unknown PT':
                asset_name = 'Unknown'

            sheet_name = f"{chain_name}-{asset_name}"

            if sheet_name not in pts_by_asset:
                pts_by_asset[sheet_name] = []
            pts_by_asset[sheet_name].append(pt)

        # Export each asset type to its own worksheet
        for sheet_name, pts in pts_by_asset.items():
            worksheet = self.get_or_create_worksheet(spreadsheet, sheet_name)

            # Convert to DataFrame
            df = self.format_data_for_sheets(pts)

            try:
                if append_data:
                    # FILO: Insert new data at the top (row 2), pushing existing data down
                    existing_data = worksheet.get_all_records()
                    if existing_data:
                        # Insert new data at row 2 (after headers)
                        print(f"📊 Inserting {len(pts)} PT records at top (FILO order)")

                        # Convert DataFrame to list of lists for insertion
                        values = df.values.tolist()

                        # Insert rows to make space for new data
                        worksheet.insert_rows(values, row=2)
                    else:
                        # No existing data, write from row 2
                        print(f"📊 Writing {len(pts)} PT records to new sheet")
                        set_with_dataframe(worksheet, df, row=2, include_index=False, include_column_header=False)
                else:
                    # Replace all data
                    print(f"📊 Replacing sheet data with {len(pts)} PT records")
                    worksheet.clear()
                    set_with_dataframe(worksheet, df, include_index=False)

                print(f"✅ Successfully exported {len(pts)} PT records to {sheet_name} sheet")

            except Exception as e:
                print(f"❌ Error writing to sheet {sheet_name}: {e}")
                continue

        print(f"🎉 Export completed! View at: https://docs.google.com/spreadsheets/d/{spreadsheet.id}")

    def is_available(self) -> bool:
        """Check if Google Sheets functionality is available."""
        return SHEETS_AVAILABLE

    def get_service_account_email(self) -> Optional[str]:
        """Get the service account email for sharing instructions."""
        if not self.credentials_file or not os.path.exists(self.credentials_file):
            return None

        try:
            with open(self.credentials_file, 'r') as f:
                creds_info = json.load(f)
                return creds_info.get('client_email')
        except:
            return None