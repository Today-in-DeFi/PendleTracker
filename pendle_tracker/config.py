"""Configuration management for Pendle PT tracker."""

import os
import json
from pathlib import Path
from typing import Dict, List, Any, Optional
from dotenv import load_dotenv

load_dotenv()


class Config:
    """Configuration manager for Pendle PT tracker."""

    def __init__(self):
        self.env_config = {
            'api_base_url': os.getenv('PENDLE_API_BASE_URL', 'https://api-v2.pendle.finance/core'),
            'default_chain_id': int(os.getenv('DEFAULT_CHAIN_ID', '1')),
            'rate_limit_rpm': int(os.getenv('RATE_LIMIT_RPM', '60')),
            'default_historical_days': int(os.getenv('DEFAULT_HISTORICAL_DAYS', '7')),
            'alert_threshold_percent': float(os.getenv('ALERT_THRESHOLD_PERCENT', '15')),
            'default_output_format': os.getenv('DEFAULT_OUTPUT_FORMAT', 'table'),
            'enable_colors': os.getenv('ENABLE_COLORS', 'true').lower() != 'false',
            'google_credentials_file': os.getenv('GOOGLE_CREDENTIALS_FILE', 'Google Credentials.json'),
            'google_sheet_id': os.getenv('GOOGLE_SHEET_ID'),
            'google_sheet_name': os.getenv('GOOGLE_SHEET_NAME', 'Pendle PT Tracker')
        }

        self.config_file_data: Optional[Dict] = None
        self.cli_args: Dict[str, Any] = {}

    def load_config_file(self, config_path: str) -> bool:
        """Load configuration from JSON file."""
        try:
            config_file = Path(config_path)
            if not config_file.exists():
                print(f"Warning: Configuration file not found: {config_path}")
                return False

            with open(config_file, 'r') as f:
                self.config_file_data = json.load(f)
            return True
        except Exception as e:
            print(f"Warning: Could not load config file {config_path}: {e}")
            return False

    def set_cli_args(self, args: Dict[str, Any]):
        """Set CLI arguments."""
        self.cli_args = {k: v for k, v in args.items() if v is not None}

    def get(self, key: str, default: Any = None) -> Any:
        """Get configuration value with priority: CLI args > config file > environment > default."""
        # Check CLI args first
        if key in self.cli_args:
            return self.cli_args[key]

        # Check config file
        if self.config_file_data and key in self.config_file_data:
            return self.config_file_data[key]

        # Check environment config
        if key in self.env_config:
            return self.env_config[key]

        return default

    def get_pts(self) -> List[Dict[str, Any]]:
        """Get PT configurations."""
        # Single PT from CLI
        if 'pt' in self.cli_args:
            return [{
                'name': 'CLI PT',
                'market_address': self.cli_args['pt'],
                'chain_id': self.get('chain_id', self.env_config['default_chain_id']),
                'enabled': True
            }]

        # Multiple PTs from config file
        if self.config_file_data and 'pts' in self.config_file_data:
            return [pt for pt in self.config_file_data['pts'] if pt.get('enabled', True)]

        return []

    def get_preferences(self) -> Dict[str, Any]:
        """Get user preferences."""
        defaults = {
            'output_format': self.env_config['default_output_format'],
            'show_historical': False,
            'historical_days': self.env_config['default_historical_days'],
            'sort_by': 'implied_apy',
            'sort_order': 'desc'
        }

        if self.config_file_data and 'preferences' in self.config_file_data:
            return {**defaults, **self.config_file_data['preferences']}

        return defaults

    def get_alert_config(self) -> Dict[str, Any]:
        """Get alert configuration."""
        defaults = {
            'enabled': False,
            'thresholds': {
                'implied_apy_min': 0,
                'implied_apy_max': 100,
                'liquidity_min': 0
            }
        }

        if self.config_file_data and 'alerts' in self.config_file_data:
            return {**defaults, **self.config_file_data['alerts']}

        return defaults


# Global config instance
config = Config()