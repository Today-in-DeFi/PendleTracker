# PendleTracker

Standalone Pendle PT/YT/LP watchlist producer. SQLite under `data/pendle.db` is
the source of truth; `data/pendle_markets.json` is the committed feed projection.
Direct PT holdings are derived from the riskAnalyst portfolio feed at
`/home/danger/riskAnalyst/data/portfolio/pendle_positions.json`; collateral-only
PT exposures remain curated in `pendle_tracker/watchlist.py`.

## Outputs

- `data/pendle.db` - local SQLite market/time-series store, ignored by git
- `data/pendle_markets.json` - latest watchlist snapshot projection, committed
- `data/pendle_index_latest.json` - legacy configured-chain index projection, with per-market collection clocks and maturity recalculated at projection time
- `data/pendle_alert_state.json` - local alerter state

The P0 schema is compatible with PegTracker's former `data/pendle_markets.json`
contract.

## Setup

```bash
python3 -m pip install -r requirements.txt
```

Telegram alerts use `telegram_config.json`, matching the copied
`pendle_risk_alerter.py` behavior from PegTracker.

## Usage

Write a fresh snapshot, append SQLite history, and regenerate the JSON feed:

```bash
python3 -m pendle_tracker snapshot
```

List the latest records from `data/pendle_markets.json`:

```bash
python3 -m pendle_tracker list
```

Query a market:

```bash
python3 -m pendle_tracker query --market PT-srUSDat-27AUG2026
```

Run the risk alerter without sending Telegram messages:

```bash
python3 pendle_risk_alerter.py --dry-run
```

Refresh the broad Ethereum active-market index:

```bash
python3 -m pendle_tracker index
```

Rank indexed markets:

```bash
python3 -m pendle_tracker top --by implied_apy --n 20
```

## Cron

`cron_pendle_tracker.sh` runs the standalone producer flow:

1. `python3 -m pendle_tracker snapshot`
2. `python3 pendle_risk_alerter.py`
3. write `logs/pendle_tracker_YYYYMMDD.log`
4. prune logs older than 30 days

Install it hourly with the scheduler used on the host.

## Legacy Sheets Code

The old Google Sheets implementation is archived under `_legacy/`. It is no
longer the active runtime path.

## Storage Notes

`data/pendle.db` is ignored because it grows on every run. A clean git tree only
means the committed projection is clean; verify DB state directly with `sqlite3`
when checking runtime correctness.

The broad index sweep is meant for a lower cadence than the hourly watchlist
snapshot. Installing that cadence is a host crontab change outside this repo.


## Cross-chain PT research inventory

The explicit inventory exporter uses the official cross-chain market directory
(`/core/v2/markets/all`), paginated at 100 records, and `/core/v1/chains`.
It resolves PT/YT/SY metadata through the asset directory and reads market details
for unexpired markets to resolve underlying/accounting metadata and `dataUpdatedAt`.
Calls share a throttle below 60 requests/minute. A full run takes roughly two
minutes, depending on directory size and API retries.

```bash
python3 export_pt_inventory.py --out data/pendle_pt_inventory_latest.json --legacy-index data/pendle_index_latest.json --raw-out /tmp/pendle-pt-inventory-raw.json
```

The output is an inventory, not a ranked or risk-screened farm list. It includes
historical entries with explicit expiry/quality states; expired-market metadata
is not enriched. `current_inventory(payload)` returns quality-ready records with
at least seven days remaining and current collection/source clocks, recalculated
at consumption time. It applies no risk, liquidity or yield floor.

Freshness uses the detail endpoint's `dataUpdatedAt`, not the directory's older
`timestamp` metadata. HTTP retrieval and upstream source clocks are separate.
The reported liquidity is market liquidity value, not executable exit depth.
Accounting references can be virtual/scaled asset identifiers; they are not
verified cash-redemption tokens. SY redemption routing still needs validation.
LP incentives and YT/points yields never enter the PT implied-APY field.

This exporter does not write SQLite, holdings snapshots, alert state, Sheets or
schedules. No new cron job is installed. The legacy index projection separately
recomputes cached expiry/day fields and publishes stored collection timestamps;
its historical upstream quote-update clocks are unavailable and remain null.
Consumers must re-evaluate expiry and source ages rather than trusting cached
status strings forever.

Run the focused fixture and quality checks with:

```bash
python3 -m pytest -q tests/test_pt_inventory.py
```
