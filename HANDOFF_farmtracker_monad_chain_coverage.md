# Handoff: enable **Monad (143)** so the srUSDat PT resolves

**From:** FarmTracker (Claude session, 2026-08-21)
**For:** PendleTracker Claude. Self-contained.

## What's happening

FarmTracker's `Personal USD` holds **`PT-srUSDat-14JAN2027`** on Monad — $52,991,
its largest PT. It reaches you in the feed, and you drop it:

```
[Pendle portfolio] skipping position with unknown chain 'monad': PT-srUSDat-14JAN2027
```

`portfolio.py:248` calls `_chain_id(pos.get("chain"))` → `normalize_chain()` →
`CHAIN_ALIASES` (index.py:30), which has no `monad` key, so the position is
skipped before the index lookup at line 257 is ever reached.

Downstream, FarmTracker's daily digest calls
`pendle_tracker.get_position_enrichment()` for every PT. For this one it gets
`None`, so the position shows **no maturity countdown, no fixed APY, and no exit-
liquidity line** — while every eth/bnb PT in the same digest shows all three.

## What we need

Two one-line changes in `pendle_tracker/index.py`:

```python
CHAINS = [1, 56, 143]          # was [1, 56]

CHAIN_ALIASES = {
    ...
    "monad": 143, "143": 143, 143: 143,      # new
}
```

Both are needed and neither works alone: without the alias the position is
skipped at the chain gate; without `CHAINS` the sweep never indexes Monad
markets, so the `(143, pt_address)` lookup misses and it is skipped one line
later instead.

## Verification data (live, 2026-08-21)

Pendle serves Monad as chain **143**. `GET /core/v1/143/markets/active` returns
**8 active markets**, one of which is ours:

```
name              srUSDat
market_address    0xc945210f85b55946eb970f427e4b9150fff600de
pt                143-0x355e82c60d51d6942bdfd0f2b95a204acd068963
yt                143-0x0435a599e3fcf2e53028760060499350e25c3dd2
sy                143-0xa544d9b7961d1db86ab81e9e3fa5659838c28b51
underlyingAsset   143-0x17b8f7373ecd556192abfc85be314e5d4fb6b3fa
expiry            2027-01-14T00:00:00.000Z
impliedApy        0.14311      aggregatedApy  0.17825
liquidity         $115,959.76
```

That `pt` address matches FarmTracker's stored `contract_address` for the
position exactly, so the `(chain_id, pt_address)` join will land once the chain
is enabled.

**Sweep cost is 8 markets.** Your `CHAINS` comment warns that each added chain
lengthens the sequential sweep against the global 60 rpm budget — at
`MIN_CALL_INTERVAL_SEC = 1.05` this is single-digit seconds, the cheapest of the
three chains. (Arbitrum, the one already commented out as a candidate, is far
larger.)

## Why this one matters more than the usual coverage gap

Market liquidity is **$115,960** and our position is **$52,991** — we are ~46% of
the pool. Exit slippage at our notional is exactly the number your enrichment
exists to surface, and it is the one PT in the book where it is load-bearing.
Right now it is the one PT where nothing is shown at all.

## Out of scope for you

- The position's **entry APY**. We source that from the Pendle limit order that
  filled it (`buy_pt`, `lnImpliedRate` → 11.70%, filled 2026-08-20T02:57:48Z) via
  FarmTracker's own `shared/pendle_api.get_fill_implied_apy`. Not your concern —
  noting it so you don't add a second, conflicting entry-rate source.
- FarmTracker's PT `current_apy` (15.63%) is its own ratio-to-maturity calc and
  deliberately differs from Pendle's `impliedApy` (14.31%). We are not asking you
  to reconcile them.

## Deliverable

Both lines changed and one index sweep run, such that:

```python
import pendle_tracker
pendle_tracker.get_position_enrichment("PT-srUSDat-14JAN2027", max_age_hours=6)
# currently: None
# wanted:    dict with days_to_maturity, fixed_apy, exit_slippage_bps_at_notional
```

Ping the FarmTracker session and we will re-verify through
`shared/pendle_enrichment.get_pt_enrichment()`.

— End of handoff.
