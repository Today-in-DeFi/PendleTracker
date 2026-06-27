"""
Pendle PT/YT/LP tracking — standalone package.

Public API:
  - snapshot()            run the watchlist, write data/pendle_markets.json + history
  - get_market(key)       latest record for one market (in-process analyzer use)
  - query(...)            ad-hoc lookups (CLI)

The outward contract is this module's public functions plus the published JSON
files under data/.
"""

from .collector import (
    snapshot,
    get_market,
    query,
    build_market_record,
    get_position_enrichment,
    format_pt_summary,
)
from .watchlist import WATCHLIST, get_entry

__all__ = [
    "snapshot",
    "get_market",
    "query",
    "build_market_record",
    "get_position_enrichment",
    "format_pt_summary",
    "WATCHLIST",
    "get_entry",
]
