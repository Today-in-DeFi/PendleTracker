"""Pendle API client with rate limiting."""

import time
import asyncio
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
import requests
from .config import config


class RateLimiter:
    """Rate limiter for API requests."""

    def __init__(self, requests_per_minute: int = 60):
        self.requests_per_minute = requests_per_minute
        self.requests: List[float] = []
        self.interval_seconds = 60.0

    def acquire(self):
        """Acquire permission to make a request."""
        now = time.time()

        # Remove requests older than 1 minute
        self.requests = [req_time for req_time in self.requests
                        if now - req_time < self.interval_seconds]

        if len(self.requests) >= self.requests_per_minute:
            oldest_request = min(self.requests)
            wait_time = self.interval_seconds - (now - oldest_request) + 0.1  # Add buffer

            print(f"Rate limit reached. Waiting {wait_time:.1f}s...")
            time.sleep(wait_time)

            return self.acquire()  # Retry after waiting

        self.requests.append(now)


class PendleAPIClient:
    """Client for interacting with Pendle API."""

    def __init__(self):
        self.base_url = config.get('api_base_url')
        self.rate_limiter = RateLimiter(config.get('rate_limit_rpm'))
        self.session = requests.Session()

        self.session.headers.update({
            'Content-Type': 'application/json',
            'User-Agent': 'pendle-tracker/1.0.0'
        })

    def _make_request(self, method: str, endpoint: str, **kwargs) -> Dict:
        """Make a rate-limited API request."""
        self.rate_limiter.acquire()

        url = f"{self.base_url}{endpoint}"

        try:
            response = self.session.request(method, url, timeout=30, **kwargs)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.HTTPError as e:
            if response.status_code == 429:
                print("Rate limit exceeded by server, waiting...")
                time.sleep(60)
                return self._make_request(method, endpoint, **kwargs)
            else:
                raise Exception(f"API Error {response.status_code}: {response.text}")
        except requests.exceptions.RequestException as e:
            raise Exception(f"Network error: {e}")

    def get_active_markets(self, chain_id: int = 1) -> Dict:
        """Get all active Pendle markets."""
        endpoint = f"/v1/{chain_id}/markets/active"
        response = self._make_request('GET', endpoint)

        # Handle different response structures
        if 'markets' in response:
            return {'results': response['markets']}
        return response

    def get_market_data(self, market_address: str, chain_id: int = 1) -> Dict:
        """Get current market data for a specific PT."""
        endpoint = f"/v2/{chain_id}/markets/{market_address}/data"
        return self._make_request('GET', endpoint)

    def get_historical_data(self, market_address: str, chain_id: int = 1,
                          timeframe: str = 'week') -> Optional[Dict]:
        """Get historical market data."""
        endpoint = f"/v1/{chain_id}/markets/{market_address}/historical-data"
        params = {'timeframe': timeframe}

        try:
            return self._make_request('GET', endpoint, params=params)
        except Exception as e:
            print(f"Warning: Could not fetch historical data: {e}")
            return None

    def get_market_info(self, market_address: str, chain_id: int = 1) -> Dict:
        """Get comprehensive market information."""
        try:
            # Get detailed APY data from v2 endpoint
            current_data = self.get_market_data(market_address, chain_id)

            # Get PT info (name, symbol, expiry) from v1 active markets
            pt_info = self.get_pt_info(market_address, chain_id)

            # Get historical data
            historical_data = self.get_historical_data(market_address, chain_id)

            return {
                'current': current_data,
                'pt_info': pt_info,
                'historical': historical_data
            }
        except Exception as e:
            raise Exception(f"Failed to fetch market info for {market_address}: {e}")

    def get_pt_info(self, market_address: str, chain_id: int = 1) -> Optional[Dict]:
        """Get PT information (name, symbol, expiry) from active markets."""
        try:
            active_markets = self.get_active_markets(chain_id)

            if 'results' in active_markets:
                for market in active_markets['results']:
                    if market.get('address', '').lower() == market_address.lower():
                        return {
                            'name': market.get('name', 'Unknown'),
                            'symbol': market.get('name', 'Unknown'),  # Using name as symbol for now
                            'expiry': market.get('expiry'),
                            'pt_address': market.get('pt'),
                            'yt_address': market.get('yt'),
                            'sy_address': market.get('sy'),
                            'underlying_asset': market.get('underlyingAsset')
                        }

            return None
        except Exception as e:
            print(f"Warning: Could not fetch PT info: {e}")
            return None

    def search_markets(self, query: str, chain_id: int = 1) -> List[Dict]:
        """Search for markets by PT symbol or address."""
        try:
            active_markets = self.get_active_markets(chain_id)

            if not active_markets or 'results' not in active_markets:
                return []

            query_lower = query.lower()
            results = []

            for market in active_markets['results']:
                # Search by PT symbol
                if (market.get('pt', {}).get('symbol', '').lower().find(query_lower) != -1 or
                    market.get('address', '').lower().find(query_lower) != -1):
                    results.append(market)

            return results
        except Exception as e:
            raise Exception(f"Failed to search markets: {e}")

    def close(self):
        """Close the session."""
        self.session.close()