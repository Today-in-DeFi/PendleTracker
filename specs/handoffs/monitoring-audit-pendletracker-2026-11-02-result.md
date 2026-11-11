# Pendle monitoring audit implementation — 2026-11-02

Implemented locally; no manual Telegram sends, trades or owner messages.

## Changes

- `pendle_risk_alerter.py`: settlement-aware maturity wording, no mandatory roll/exit or universal 1:1 claim; watch removal is not proof of closure. Durable delivery outbox checkpoints each accepted Telegram message and commits target alert state after all messages succeed. A lost server response can still cause a duplicate retry: Telegram provides no client idempotency key. Unknown/incomplete holdings coverage emits a coverage transition and blocks removal-based clears. Market snapshot errors also block clears.
- `pendle_tracker/portfolio.py`: separate upstream and consumer clocks, missing/invalid/future/stale source guards, conservative partial resolution, persistent direct watchlist cache including verified empty. A complete fresh feed can remove exited positions; failed or partial resolution retains previous exposures. No new upstream portfolio exporter.
- `pendle_tracker/db.py`: publishes holdings coverage and dependency metadata; uses current resolved watchlist notional instead of a historical per-market position summary.
- `pendle_tracker/watchlist.py`: two expired legacy collateral entries explicitly marked `dependency_review`, current borrower exposure unverified, owner risk alerts suppressed, review due 2026-11-09. Market observations remain; no zero-exposure claim or retirement. Current source evidence found only market inventory, not complete current borrower collateral balances. Current exposure verification remains open.
- `pendle_tracker/collector.py`: corrected maturity flags; skips expired swap simulations because the API rejects them. Redemption and swap liquidity remain distinct.
- `pendle_digest.py`: upstream/sync timestamps, same-day source warning, missing/future/stale clock banners, dependency review warning, explicit srUSDat output and separate conversion/queue/bridge/liquidity stages. Added Monad address-index enrichment alias.
- `cron_pendle_digest.sh`: documents supported upstream sequence. Live existing cron changed from `0 9 * * * /home/danger/PendleTracker/cron_pendle_digest.sh` to `50 9 * * * /home/danger/PendleTracker/cron_pendle_digest.sh`; exact full crontab readback matched the intended single-line replacement. No other schedules changed. No CRON_TZ override was found in the relevant schedule review.

## Validation

`python3 -m unittest discover -s tests -v` — 14 tests pass: fresh/empty/partial/stale/missing/index failure, source timestamp validity, cache empty persistence, dependency suppression, coverage failure transition, delivery failure/retry/no repeated success, partial message resume, maturity/removal wording and digest entry/exit membership.

Python compilation, shell syntax and git whitespace checks pass. Current resolver found all four direct positions with complete coverage. A live snapshot-only refresh returned six markets, zero collection errors and holdings source clocks 2026-11-02 01:20:14 UTC upstream / 01:21:14 UTC consumer sync. Final expired-quote guard was verified separately with a mocked client. Alerter `--dry-run` and digest `--print` rendered successfully without sending or changing acknowledged alert state.

The 09:50 schedule is installed and read back, but the next morning execution has not yet occurred. Same-day entry/exit behavior was demonstrated with fixtures; no real holdings were changed. Existing unrelated index/snapshot JSON edits were present before this task; index edits were left untouched. Snapshot was refreshed as part of validation.

## Remaining evidence work

Establish complete current downstream exposure for the two legacy August collateral markets, including the exposure source clock. Until then they remain explicitly unverified review dependencies, not proven active collateral and not proven closed. The review date is metadata, not a new schedule. Contract-specific redemption amounts are not calculated here; wording points to PY-index/SY conversion instead of asserting unsupported units or settlement times.
