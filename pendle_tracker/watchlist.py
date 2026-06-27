"""
Curated Pendle watchlist — markets we have direct or indirect exposure to.

Configured by *market address* (not symbol): a Pendle market is maturity-specific,
so when a PT matures the entry must be rolled to the new market address. The
`expiry` field is documentation only — authoritative expiry comes from the API.

Exposure ground truth: ~/riskAnalyst/data/portfolio (2026-06-26).
See specs/pendle-pt-tracking-pegtracker.md.
"""

CHAIN_ID = 1  # ethereum

# Notional ladder (USD) for the exit-slippage simulation, in addition to each
# market's own `our_notional_usd`.
SLIPPAGE_LADDER_USD = [10_000, 50_000, 100_000]

# Read-only receiver for SDK swap quotes. Must be a syntactically valid address
# (zero-ish 0x..01 is rejected by the API). Uses the DAI contract address purely
# as a known-valid checksummed address; no tx is ever sent.
SWAP_RECEIVER = "0x6B175474E89094C44Da98b954EedeAC495271d0F"

WATCHLIST = [
    {
        "key": "PT-srUSDat-27AUG2026",
        "market": "0x4237a8acbd0b5a2dec4aa83b1fd83f20162d02b8",
        "chain": 1,
        "underlier": "srUSDat",
        "exposure": "direct",          # we hold this PT
        "our_notional_usd": 52_907,
        "expiry": "2026-08-27",
    },
    {
        "key": "PT-apxUSD-5NOV2026",
        "market": "0xaf0349fb9b1ba07d34381870c59b560b31412660",
        "chain": 1,
        "underlier": "apxUSD",
        "exposure": "direct",
        "our_notional_usd": 31_035,
        "expiry": "2026-11-05",
    },
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


def get_entry(key):
    for e in WATCHLIST:
        if e["key"] == key:
            return e
    return None
