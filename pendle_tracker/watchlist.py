"""
Pendle watchlist — direct holdings from the portfolio feed plus curated
collateral-exposure markets.

Direct holdings resolve by exact PT token address through the broad market index.
Collateral entries remain hand-listed because those PTs sit inside other
protocols and do not appear as wallet holdings.

Feed source: /home/danger/riskAnalyst/data/portfolio/pendle_positions.json.
"""

CHAIN_ID = 1  # ethereum

# Notional ladder (USD) for the exit-slippage simulation, in addition to each
# market's own `our_notional_usd`.
SLIPPAGE_LADDER_USD = [10_000, 50_000, 100_000]

# Read-only receiver for SDK swap quotes. Must be a syntactically valid address
# (zero-ish 0x..01 is rejected by the API). Uses the DAI contract address purely
# as a known-valid checksummed address; no tx is ever sent.
SWAP_RECEIVER = "0x6B175474E89094C44Da98b954EedeAC495271d0F"

COLLATERAL_WATCHLIST = [
    {
        "key": "PT-sUSDE-13AUG2026",
        "market": "0x177768caf9d0e036725a51d3f60d7e20f2d4d194",
        "chain": 1,
        "underlier": "sUSDe",
        "exposure": "collateral",      # backs syrupUSDC/syrupUSDT + ethena DeFi
        "our_notional_usd": None,
        "expiry": "2026-08-13",
    },
    {
        "key": "PT-USDE-13AUG2026",
        "market": "0x43c97094da0e894d3af2fda6f507d59a29888251",
        "chain": 1,
        "underlier": "USDe",
        "exposure": "collateral",
        "our_notional_usd": None,
        "expiry": "2026-08-13",
    },
]

# Backwards-compatible module constant. Runtime snapshot paths call
# get_watchlist(), which derives direct holdings from the portfolio feed.
WATCHLIST = list(COLLATERAL_WATCHLIST)


def get_watchlist(write_positions=True):
    try:
        from .portfolio import derive_direct_watchlist
        direct = derive_direct_watchlist(write_positions=write_positions)
    except Exception as exc:  # keep snapshots from blanking if the feed path breaks
        import logging
        logging.getLogger(__name__).warning(f"[Pendle watchlist] using curated-only fallback: {exc}")
        direct = []

    seen = set()
    out = []
    for entry in [*direct, *COLLATERAL_WATCHLIST]:
        market = entry["market"].lower()
        if market in seen:
            continue
        seen.add(market)
        out.append(entry)
    return out


def get_entry(key):
    for e in get_watchlist(write_positions=False):
        if e["key"] == key:
            return e
    return None
