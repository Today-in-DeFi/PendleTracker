"""
Pendle hosted-API wrapper (the adapter).

Thin, typed access to the three Pendle endpoints we need. All field mappings
verified live 2026-06-26 (chain 1). See specs/pendle-pt-tracking-pegtracker.md.
"""

import logging
import time
from typing import Optional, Dict, Any

import requests

logger = logging.getLogger(__name__)

BASE = "https://api-v2.pendle.finance/core"
TIMEOUT = 25
RETRIES = 3
RETRY_SLEEP = 1.5


class PendleAPIError(Exception):
    pass


class PendleClient:
    def __init__(self, base: str = BASE, timeout: int = TIMEOUT):
        self.base = base.rstrip("/")
        self.timeout = timeout
        self._session = requests.Session()
        self._session.headers.update({"accept": "application/json"})

    def _get(self, path: str, params: Optional[dict] = None) -> dict:
        url = f"{self.base}{path}"
        last_exc = None
        for attempt in range(1, RETRIES + 1):
            try:
                r = self._session.get(url, params=params, timeout=self.timeout)
                if r.status_code >= 400:
                    # Surface the API's error body for diagnosis; don't retry 4xx.
                    body = r.text[:300]
                    if 400 <= r.status_code < 500:
                        raise PendleAPIError(f"{r.status_code} {url} :: {body}")
                    raise requests.HTTPError(f"{r.status_code} {body}")
                return r.json()
            except (requests.RequestException, ValueError) as exc:
                last_exc = exc
                if attempt < RETRIES:
                    time.sleep(RETRY_SLEEP * attempt)
        raise PendleAPIError(f"GET {url} failed after {RETRIES} attempts: {last_exc}")

    # --- endpoints -------------------------------------------------------

    def market_data(self, chain: int, market: str) -> dict:
        """v2 market data: APYs, liquidity, TVL, volume, reserves, ptDiscount."""
        return self._get(f"/v2/{chain}/markets/{market}/data")

    def market_detail(self, chain: int, market: str) -> dict:
        """v1 market detail: pt/yt/sy/underlyingAsset objects (addr, price, decimals)."""
        return self._get(f"/v1/{chain}/markets/{market}")

    def active_markets(self, chain: int) -> list:
        d = self._get(f"/v1/{chain}/markets/active")
        return d.get("markets", d if isinstance(d, list) else [])

    def swap_price_impact(
        self,
        chain: int,
        market: str,
        token_in: str,
        token_out: str,
        amount_in_raw: int,
        receiver: str,
        slippage: float = 0.05,
    ) -> Optional[float]:
        """
        Simulate a swap and return the price impact as a signed fraction
        (e.g. -0.0004 = -4bps). Returns None on failure (e.g. insufficient
        liquidity for the requested size).
        """
        try:
            d = self._get(
                f"/v2/sdk/{chain}/markets/{market}/swap",
                params={
                    "receiver": receiver,
                    "slippage": slippage,
                    "tokenIn": token_in,
                    "tokenOut": token_out,
                    "amountIn": int(amount_in_raw),
                },
            )
        except PendleAPIError as exc:
            logger.warning(f"[Pendle] swap sim failed ({market} size={amount_in_raw}): {exc}")
            return None
        data = d.get("data", d)
        pi = data.get("priceImpact")
        return float(pi) if pi is not None else None
