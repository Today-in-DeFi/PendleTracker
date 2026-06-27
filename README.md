# PendleTracker

Standalone Pendle PT/YT/LP watchlist producer. SQLite under `data/pendle.db` is
the source of truth; `data/pendle_markets.json` is the committed feed projection.
Direct PT holdings are derived from the riskAnalyst portfolio feed at
`/home/danger/riskAnalyst/data/portfolio/pendle_positions.json`; collateral-only
PT exposures remain curated in `pendle_tracker/watchlist.py`.

## Outputs

- `data/pendle.db` - local SQLite market/time-series store, ignored by git
- `data/pendle_markets.json` - latest watchlist snapshot projection, committed
- `data/pendle_index_latest.json` - latest ETH active-market index projection, committed
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
