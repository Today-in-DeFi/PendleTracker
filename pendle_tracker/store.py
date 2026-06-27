"""
Pendle history store — per-market rolling time series.

Purpose-built rather than reusing JSONDatabase: the rich per-market Pendle fields
(APYs, discount, slippage ladder) don't fit JSONDatabase's peg-price schema. This
mirrors how each backing analyzer keeps its own `*_history.json` (flat entries +
30-day prune).
"""

import json
import logging
import os
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

# Fields kept per history datapoint (the snapshot carries the full record).
HISTORY_FIELDS = [
    "timestamp",
    "pt_price_usd",
    "underlying_price_usd",
    "pt_implied_apy",
    "underlying_apy",
    "pt_vs_underlying_spread",
    "yt_floating_apy",
    "pt_discount",
    "liquidity_usd",
    "total_tvl_usd",
    "days_to_maturity",
    "exit_slippage_bps_at_notional",
]


class PendleHistoryStore:
    def __init__(self, filepath: str, retain_days: int = 30):
        self.filepath = filepath
        self.retain_days = retain_days
        self.data = self._load()

    def _load(self) -> Dict[str, Any]:
        if os.path.exists(self.filepath):
            try:
                with open(self.filepath) as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning(f"[Pendle store] could not read {self.filepath}: {exc}")
        return {"markets": {}, "last_updated": None}

    def append(self, market_key: str, record: Dict[str, Any]) -> None:
        entry = {k: record.get(k) for k in HISTORY_FIELDS}
        bucket = self.data["markets"].setdefault(market_key, {"entries": []})
        bucket["entries"].append(entry)

    def prune(self) -> None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=self.retain_days)
        for bucket in self.data["markets"].values():
            kept = []
            for e in bucket["entries"]:
                ts = e.get("timestamp")
                try:
                    when = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                except (AttributeError, ValueError):
                    kept.append(e)  # keep unparseable rather than silently drop
                    continue
                if when >= cutoff:
                    kept.append(e)
            bucket["entries"] = kept

    def save(self) -> None:
        self.prune()
        self.data["last_updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        tmp = self.filepath + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self.data, f, indent=2)
        os.replace(tmp, self.filepath)

    def get_history(self, market_key: str) -> List[Dict[str, Any]]:
        return self.data.get("markets", {}).get(market_key, {}).get("entries", [])
