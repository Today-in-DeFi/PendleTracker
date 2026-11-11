PT route quote pilot

Run from /home/danger/PendleTracker:

python3 export_pt_route_quotes.py --out data/research/NEW_RUN/quotes.json --raw-dir data/research/NEW_RUN/raw

The fixed candidate manifest is candidates-2026-11-04.json. --market CHAIN:MARKET selects exact manifest entries; --max-markets bounds the pilot to at most 11. Use a new raw directory for every run. Refresh the upstream inventory separately if older than 24 hours. Each market detail, identity and expiry is checked live again before quotes.

The exporter reads inventory plus the manifest, public Pendle endpoints and public RPC. It does not import holdings resolution, use private keys, read the live DB, broadcast transactions, change schedules or send alerts. POST /v3/sdk/{chain}/convert only generates quote/calldata evidence. RPC methods are chain/block reads and eth_call; batch reads use a pinned block. All transaction calldata stays in evidence files and is never submitted.

The process lock prevents two instances of this exporter from running together. All pilot HTTP requests are sequential and spaced at least three seconds apart. Only KyberSwap is enabled when its advertised cost is <=5 CU (5 base CU plus <=5 aggregator CU, <=200 CU/min at this spacing before header backoff). No additional analytics CU or limit orders. Server CU/remaining/reset headers are retained; low remaining budget delays the next request; 429 responses back off. A second program sharing the IP has its own consumption, so headers remain authoritative. This exporter does not change the existing collector/client or its scheduling.

For each market, request USDC -> PT and PT -> USDC at $10k/$50k/$100k input valuations. USD sizing uses the explicit Pendle price response, never a hard-coded $1 assumption; amounts remain integer native units. Price receipt is recorded separately because this endpoint does not provide a per-price source clock. Failed benchmark requests remain failures. When allowed by the SY token list, native-underlying routes are separately attempted without an aggregator. Native quotes do not establish conversion into the benchmark.

The API returns point-in-time quotes and optional simulation gas. A quote without simulated gas is labelled quote/calldata only. Success does not establish a real investor's funding, approvals, allowlist access, future execution or issuer redemption rights. API quote block is unavailable and is explicitly distinct from the pinned SY-read block. Fees are preserved as SDK-reported USD fees; gas cost and net yield stay unknown. Reported market liquidity is only a dust screen. PT APY is never augmented with underlying yield, points or LP rewards.

Maturity output tokens come from current SY contract reads and advertised SDK outputs. Deposit/redeem previews are current conversion observations; they do not project a future maturity payout. Generic PY accounting converts PT raw accounting units into SY using the then-current PY index, with rounding and same-block caching. The wrapper then converts SY into supported output tokens. Subsequent swaps, issuer redemption queues and bridge/backing dependencies remain separate. SDK/onchain token list differences are reported; exact market/PT/SY/expiry mismatches stop that candidate.

Optional source refresh (Sourcify, independent of quote collection):
python3 specs/pt-routes/collect_sy_sources.py --out-dir data/research/NEW_RUN

Source registry proxy resolution is timestamped at retrieval, not cryptographically pinned to the quote's observation block. Unavailable source/implementation verification remains a coverage gap.

Official references:
https://docs.pendle.finance/pendle-v2-dev/Backend/ApiOverview
https://api-v2.pendle.finance/core/docs
https://developers.circle.com/stablecoins/usdc-contract-addresses
https://github.com/pendle-finance/pendle-core-v2-public/blob/87685c89d05087535e9b9647eeda0e3d297d1f06/contracts/core/YieldContracts/PendleYieldToken.sol

Optional unit enrichment at saved blocks:
python3 specs/pt-routes/enrich_units.py --quotes data/research/NEW_RUN/quotes.json --raw-dir data/research/NEW_RUN/units-raw --out data/research/NEW_RUN/units.json

Offline report and machine feed (with optional --retry RETRY_JSON and --units UNITS_JSON):
python3 specs/pt-routes/build_report.py --quotes data/research/NEW_RUN/quotes.json --sources data/research/NEW_RUN/sy_sources.json --out data/pendle_pt_route_quotes_latest.json --report specs/handoffs/pt-route-result.txt
