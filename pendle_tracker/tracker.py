"""PT tracking functionality."""

import re
from datetime import datetime
from typing import Dict, List, Optional, Any, Union
from .api_client import PendleAPIClient
from .config import config


class PTTracker:
    """Main PT tracking class."""

    def __init__(self):
        self.api_client = PendleAPIClient()

    def track_pt(self, market_address: str, chain_id: int = 1) -> Optional[Dict]:
        """Track a single PT market."""
        try:
            print(f"Fetching data for PT market: {market_address}")

            market_info = self.api_client.get_market_info(market_address, chain_id)

            if not market_info.get('current'):
                raise Exception('No current market data available')

            return self._process_market_data(market_info, market_address)

        except Exception as e:
            print(f"Error tracking PT {market_address}: {e}")
            return None

    def _process_market_data(self, market_info: Dict, market_address: str) -> Dict:
        """Process raw market data into structured format."""
        current = market_info['current']
        pt_info = market_info.get('pt_info', {})
        historical = market_info.get('historical')

        # Get expiry from PT info or current data
        expiry_str = pt_info.get('expiry') if pt_info else current.get('expiry')
        expiry_timestamp = None
        if expiry_str:
            try:
                # Parse ISO format expiry
                expiry_dt = datetime.fromisoformat(expiry_str.replace('Z', '+00:00'))
                expiry_timestamp = int(expiry_dt.timestamp())
            except:
                pass

        # Extract key metrics
        result = {
            'market_address': market_address,
            'timestamp': datetime.now().isoformat(),
            'pt_info': {
                'symbol': pt_info.get('symbol', 'Unknown') if pt_info else 'Unknown',
                'name': pt_info.get('name', 'Unknown PT') if pt_info else 'Unknown PT',
                'expiry': self._format_expiry(expiry_timestamp),
                'time_to_expiry': self._calculate_time_to_expiry(expiry_timestamp)
            },
            'apy_data': {
                'implied_apy': self._format_percentage(current.get('impliedApy')),
                'underlying_apy': self._format_percentage(current.get('underlyingApy')),
                'lp_apy': self._format_percentage(current.get('lpRewardApy')),  # Correct field name
                'swap_fee_apy': self._format_percentage(current.get('swapFeeApy'))
            },
            'market_metrics': {
                'total_liquidity': self._format_currency(current.get('liquidity', {}).get('usd')),
                'volume_24h': self._format_currency(current.get('tradingVolume', {}).get('usd')),
                'total_volume': self._format_currency(current.get('totalVolume')),
                'total_active_supply': self._format_currency(current.get('totalActiveSupply'))
            }
        }

        # Add historical data if available
        if historical and historical.get('results'):
            result['historical'] = self._process_historical_data(historical['results'])

        return result

    def _process_historical_data(self, historical_results: List[Dict]) -> Optional[Dict]:
        """Process historical data for trends and statistics."""
        if not historical_results:
            return None

        latest = historical_results[-1]
        oldest = historical_results[0]

        trends = {
            'implied_apy_trend': self._calculate_trend(
                oldest.get('impliedApy'), latest.get('impliedApy')
            ),
            'underlying_apy_trend': self._calculate_trend(
                oldest.get('underlyingApy'), latest.get('underlyingApy')
            ),
            'liquidity_trend': self._calculate_trend(
                oldest.get('totalLiquidity'), latest.get('totalLiquidity')
            )
        }

        # Calculate statistics
        implied_apys = [r.get('impliedApy', 0) for r in historical_results if r.get('impliedApy')]
        stats = {}

        if implied_apys:
            stats = {
                'max_implied_apy': self._format_percentage(max(implied_apys)),
                'min_implied_apy': self._format_percentage(min(implied_apys)),
                'avg_implied_apy': self._format_percentage(sum(implied_apys) / len(implied_apys))
            }

        return {
            'period': f"{len(historical_results)} data points",
            'trends': trends,
            'stats': stats
        }

    def _calculate_trend(self, old_value: Optional[float], new_value: Optional[float]) -> Dict:
        """Calculate trend between two values."""
        if old_value is None or new_value is None or old_value == 0:
            return {'direction': '→', 'change': 'N/A', 'status': 'unknown'}

        change_percent = ((new_value - old_value) / old_value) * 100
        direction = '↗' if change_percent > 0 else '↘' if change_percent < 0 else '→'
        status = 'increasing' if change_percent > 0 else 'decreasing' if change_percent < 0 else 'stable'

        return {
            'direction': direction,
            'change': self._format_percentage(abs(change_percent) / 100),
            'status': status
        }

    def _calculate_time_to_expiry(self, expiry_timestamp: Optional[int]) -> str:
        """Calculate human-readable time to expiry."""
        if not expiry_timestamp:
            return 'N/A'

        now = datetime.now().timestamp()
        time_left = expiry_timestamp - now

        if time_left <= 0:
            return 'Expired'

        days = int(time_left // (24 * 3600))
        hours = int((time_left % (24 * 3600)) // 3600)

        if days > 0:
            return f"{days}d {hours}h"
        else:
            return f"{hours}h"

    def _format_expiry(self, expiry_timestamp: Optional[int]) -> Optional[str]:
        """Format expiry timestamp to ISO string."""
        if not expiry_timestamp:
            return None
        return datetime.fromtimestamp(expiry_timestamp).isoformat()

    def _format_percentage(self, value: Optional[float]) -> str:
        """Format value as percentage."""
        if value is None or (isinstance(value, float) and (value != value)):  # Check for NaN
            return 'N/A'
        return f"{value * 100:.2f}%"

    def _format_currency(self, value: Optional[float]) -> str:
        """Format value as currency with appropriate units."""
        if value is None or (isinstance(value, float) and (value != value)):  # Check for NaN
            return 'N/A'

        if value >= 1e9:
            return f"${value / 1e9:.2f}B"
        elif value >= 1e6:
            return f"${value / 1e6:.2f}M"
        elif value >= 1e3:
            return f"${value / 1e3:.2f}K"
        else:
            return f"${value:.2f}"

    def track_multiple_pts(self, pt_configs: List[Dict]) -> List[Dict]:
        """Track multiple PT markets."""
        results = []

        for pt_config in pt_configs:
            result = self.track_pt(
                pt_config['market_address'],
                pt_config.get('chain_id', 1)
            )
            if result:
                result['config'] = pt_config
                results.append(result)

        return results

    def search_and_track(self, query: str, chain_id: int = 1) -> List[Dict]:
        """Search for PT markets and track them."""
        try:
            print(f"Searching for PT markets matching: {query}")

            markets = self.api_client.search_markets(query, chain_id)

            if not markets:
                print('No markets found matching the query')
                return []

            print(f"Found {len(markets)} matching market(s)")

            results = []
            # Limit to top 5 results to avoid overwhelming API
            for market in markets[:5]:
                result = self.track_pt(market['address'], chain_id)
                if result:
                    results.append(result)

            return results

        except Exception as e:
            print(f"Error in search and track: {e}")
            return []

    def check_alerts(self, pt_data: Dict, alert_config: Dict) -> List[str]:
        """Check for alert conditions."""
        if not alert_config.get('enabled'):
            return []

        alerts = []
        thresholds = alert_config.get('thresholds', {})

        # Parse APY values
        implied_apy_str = pt_data['apy_data']['implied_apy']
        if implied_apy_str != 'N/A':
            implied_apy = float(implied_apy_str.replace('%', ''))

            if implied_apy < thresholds.get('implied_apy_min', 0):
                alerts.append(f"⚠️  Low APY Alert: {implied_apy_str} is below threshold "
                            f"{thresholds['implied_apy_min']}%")

            if implied_apy > thresholds.get('implied_apy_max', 100):
                alerts.append(f"🚨 High APY Alert: {implied_apy_str} exceeds threshold "
                            f"{thresholds['implied_apy_max']}%")

        # Parse liquidity
        liquidity_str = pt_data['market_metrics']['total_liquidity']
        if liquidity_str != 'N/A':
            liquidity = self._parse_currency(liquidity_str)

            if liquidity < thresholds.get('liquidity_min', 0):
                alerts.append(f"📉 Low Liquidity Alert: {liquidity_str} is below threshold "
                            f"${thresholds['liquidity_min']:,}")

        return alerts

    def _parse_currency(self, currency_string: str) -> float:
        """Parse currency string back to float value."""
        if not isinstance(currency_string, str):
            return 0

        # Remove currency symbol and commas
        num_str = re.sub(r'[$,]', '', currency_string)

        # Handle multipliers
        multiplier = 1
        if 'B' in currency_string:
            multiplier = 1e9
            num_str = num_str.replace('B', '')
        elif 'M' in currency_string:
            multiplier = 1e6
            num_str = num_str.replace('M', '')
        elif 'K' in currency_string:
            multiplier = 1e3
            num_str = num_str.replace('K', '')

        try:
            return float(num_str) * multiplier
        except ValueError:
            return 0

    def close(self):
        """Clean up resources."""
        self.api_client.close()