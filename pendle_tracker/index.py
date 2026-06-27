"""Broad multi-chain Pendle market index and ranking helpers."""

import json
import logging
import os
import time
from datetime import datetime, timezone

from .client import PendleClient, PendleAPIError
from . import db
from .collector import compute_yt_analytics, compute_lp_analytics

logger = logging.getLogger(__name__)

# Config-driven chain list. Enabling a chain is a one-line change here.
# Pendle numeric chain ids: 1=ethereum, 56=bnb, 42161=arbitrum.
# Only enable chains that actually carry holdings/interest — every added chain
# lengthens the (sequential) sweep against the global 60 rpm budget.
CHAINS = [1, 56]
# CHAINS = [1, 56, 42161]  # add Arbitrum when a holding lands there.
DEFAULT_CHAIN = CHAINS[0]

# Backwards-compatible alias: legacy callers / default args reference CHAIN_ID
# as "the primary chain". The sweep itself iterates CHAINS, not CHAIN_ID.
CHAIN_ID = DEFAULT_CHAIN

# Chain-label normalization: feed/FarmTracker uses string labels, Pendle's API
# uses numeric ids. Maps both string aliases and numeric forms to the canonical
# numeric chain id.
CHAIN_ALIASES = {
    "eth": 1, "ethereum": 1, "mainnet": 1, "1": 1, 1: 1,
    "bsc": 56, "bnb": 56, "bnbchain": 56, "binance": 56, "56": 56, 56: 56,
    "arb": 42161, "arbitrum": 42161, "42161": 42161, 42161: 42161,
}


def normalize_chain(value):
    """Map a chain label/id ('eth', 'bsc', '56', 56, ...) to its numeric id.

    Returns None for unknown/missing values."""
    if value is None:
        return None
    key = value.strip().lower() if isinstance(value, str) else value
    return CHAIN_ALIASES.get(key)


INDEX_PATH = os.path.join(db.DATA_DIR, "pendle_index_latest.json")
MIN_CALL_INTERVAL_SEC = 1.05  # keep the broad sweep below Pendle's 60 rpm budget

INDEX_FIELDS = [
    "name",
    "pt_address",
    "yt_address",
    "sy_address",
    "underlying_address",
    "underlier",
    "maturity",
    "days_to_maturity",
    "expired",
    "pt_implied_apy",
    "underlying_apy",
    "yt_floating_apy",
    "aggregated_lp_apy",
    "pt_price_usd",
    "yt_price_usd",
    "pt_discount",
    "yt_breakeven_days",
    "yt_underwater",
    "yt_implied_vs_realized",
    "yt_theoretical_decay_usd_per_day",
    "lp_swap_fee_apy",
    "lp_incentive_apy",
    "lp_max_boosted_apy",
    "pt_sy_ratio",
    "composition_drift",
    "liquidity_usd",
    "total_tvl_usd",
    "trading_volume_usd",
]

RANK_FIELDS = {
    "implied_apy": "pt_implied_apy",
    "yt_floating_apy": "yt_floating_apy",
    "aggregated_lp_apy": "aggregated_lp_apy",
    "lp_max_boosted_apy": "lp_max_boosted_apy",
    "liquidity_usd": "liquidity_usd",
    "pt_discount": "pt_discount",
    "days_to_maturity": "days_to_maturity",
}


def _pct(value):
    return round(value * 100, 4) if value is not None else None


def _days_to_maturity(expiry_iso):
    if not expiry_iso:
        return None
    try:
        exp = datetime.fromisoformat(expiry_iso.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        return None
    delta = exp - datetime.now(timezone.utc)
    return round(delta.total_seconds() / 86400, 2)


def _usd(obj):
    return (obj or {}).get("usd")


def _asset_address(asset):
    if isinstance(asset, dict):
        return asset.get("address")
    if isinstance(asset, str) and "-" in asset:
        return asset.split("-", 1)[1]
    return asset


def _asset_name(asset):
    if not isinstance(asset, dict):
        return None
    return asset.get("symbol") or asset.get("name") or asset.get("simpleSymbol") or asset.get("proSymbol")


class RateLimiter:
    def __init__(self, min_interval_sec=MIN_CALL_INTERVAL_SEC):
        self.min_interval_sec = min_interval_sec
        self.last_call = None
        self.calls = 0

    def wait(self):
        if self.last_call is not None:
            elapsed = time.monotonic() - self.last_call
            if elapsed < self.min_interval_sec:
                time.sleep(self.min_interval_sec - elapsed)
        self.last_call = time.monotonic()
        self.calls += 1


def build_index_record(active_entry, detail, data=None, chain=DEFAULT_CHAIN):
    """Normalize one active market detail into the shared DB record shape."""
    data = data or {}
    pt = detail.get("pt") or {}
    yt = detail.get("yt") or {}
    sy = detail.get("sy") or {}
    underlying = detail.get("underlyingAsset") or {}
    expiry = detail.get("expiry") or active_entry.get("expiry")
    days = _days_to_maturity(expiry)
    name = (
        pt.get("symbol")
        or pt.get("name")
        or detail.get("proSymbol")
        or detail.get("simpleSymbol")
        or active_entry.get("name")
    )
    underlier = _asset_name(underlying) or active_entry.get("name")

    pt_implied = _pct(data.get("impliedApy", detail.get("impliedApy")))
    underlying_apy = _pct(data.get("underlyingApy", detail.get("underlyingApy")))
    spread = (
        round(pt_implied - underlying_apy, 4)
        if pt_implied is not None and underlying_apy is not None
        else None
    )
    pt_discount = data.get("ptDiscount", detail.get("ptDiscount"))

    yt_floating_apy = _pct(data.get("ytFloatingApy", detail.get("ytFloatingApy")))
    yt_price_usd = _usd(yt.get("price"))
    underlying_price_usd = _usd(underlying.get("price"))

    record = {
        "key": name,
        "exposure": None,
        "chain": detail.get("chainId") or chain,
        "market_address": detail.get("address") or active_entry["address"],
        "underlier": underlier,
        "maturity": expiry,
        "days_to_maturity": days,
        "expired": days is not None and days <= 0,
        "our_notional_usd": None,
        "pt_address": _asset_address(pt) or _asset_address(active_entry.get("pt")),
        "yt_address": _asset_address(yt) or _asset_address(active_entry.get("yt")),
        "sy_address": _asset_address(sy) or _asset_address(active_entry.get("sy")),
        "underlying_address": _asset_address(underlying) or _asset_address(active_entry.get("underlyingAsset")),
        "pt_implied_apy": pt_implied,
        "underlying_apy": underlying_apy,
        "yt_floating_apy": yt_floating_apy,
        "pt_vs_underlying_spread": spread,
        "aggregated_lp_apy": _pct(data.get("aggregatedApy", detail.get("aggregatedApy"))),
        "pt_price_usd": _usd(pt.get("price")),
        "yt_price_usd": yt_price_usd,
        "sy_price_usd": _usd(sy.get("price")),
        "underlying_price_usd": underlying_price_usd,
        "pt_discount": round(pt_discount * 100, 4) if pt_discount is not None else None,
        "liquidity_usd": _usd(data.get("liquidity", detail.get("liquidity"))),
        "total_tvl_usd": _usd(data.get("totalTvl", detail.get("totalTvl"))),
        "trading_volume_usd": _usd(data.get("tradingVolume", detail.get("tradingVolume"))),
        "total_pt": data.get("totalPt", detail.get("totalPt")),
        "total_sy": data.get("totalSy", detail.get("totalSy")),
        "exit_slippage_ladder": [],
        "exit_slippage_bps_at_notional": None,
        "fetched_at": db.utc_now(),
    }
    record.update(compute_yt_analytics(
        yt_price_usd=yt_price_usd,
        underlying_apy=underlying_apy,
        underlying_price_usd=underlying_price_usd,
        days_to_maturity=days,
        yt_floating_apy=yt_floating_apy,
    ))
    record.update(compute_lp_analytics(data, record["total_pt"], record["total_sy"]))
    return record


def _latest_index_rows(chain=DEFAULT_CHAIN):
    conn = db.ensure_db()
    try:
        rows = conn.execute(
            """
            SELECT m.*, s.*
            FROM markets m
            JOIN market_snapshots s ON s.id = (
              SELECT id FROM market_snapshots
              WHERE market_address = m.market_address
              ORDER BY ts DESC, id DESC
              LIMIT 1
            )
            WHERE m.chain = ?
            ORDER BY m.name ASC
            """,
            (chain,),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def _db_chains():
    """Distinct chains present in the markets table (so the index projection is
    always a complete reflection of the DB, regardless of which subset was last
    swept)."""
    conn = db.ensure_db()
    try:
        return [
            r[0]
            for r in conn.execute(
                "SELECT DISTINCT chain FROM markets WHERE chain IS NOT NULL ORDER BY chain"
            )
        ]
    finally:
        conn.close()


def _project_chain_markets(chain):
    rows = _latest_index_rows(chain=chain)
    markets = {}
    latest_ts = None
    for row in rows:
        address = row["market_address"]
        item = {
            "name": row["name"],
            "pt_address": row["pt_address"],
            "yt_address": row["yt_address"],
            "sy_address": row["sy_address"],
            "underlying_address": row["underlying_address"],
            "underlier": row["underlier"],
            "maturity": row["maturity"],
            "days_to_maturity": row["days_to_maturity"],
            "expired": bool(row["expired"]),
            "pt_implied_apy": row["pt_implied_apy"],
            "underlying_apy": row["underlying_apy"],
            "yt_floating_apy": row["yt_floating_apy"],
            "aggregated_lp_apy": row["aggregated_lp_apy"],
            "pt_price_usd": row["pt_price_usd"],
            "yt_price_usd": row["yt_price_usd"],
            "pt_discount": row["pt_discount"],
            "yt_breakeven_days": row["yt_breakeven_days"],
            "yt_underwater": (None if row["yt_underwater"] is None else bool(row["yt_underwater"])),
            "yt_implied_vs_realized": row["yt_implied_vs_realized"],
            "yt_theoretical_decay_usd_per_day": row["yt_theoretical_decay_usd_per_day"],
            "lp_swap_fee_apy": row["lp_swap_fee_apy"],
            "lp_incentive_apy": row["lp_incentive_apy"],
            "lp_max_boosted_apy": row["lp_max_boosted_apy"],
            "pt_sy_ratio": row["pt_sy_ratio"],
            "composition_drift": row["composition_drift"],
            "liquidity_usd": row["liquidity_usd"],
            "total_tvl_usd": row["total_tvl_usd"],
            "trading_volume_usd": row["trading_volume_usd"],
        }
        markets[address] = item
        latest_ts = max(latest_ts, row["ts"]) if latest_ts else row["ts"]
    return markets, latest_ts


def project_index(chains=None):
    """Project the latest DB rows into the multi-chain index shape.

    Defaults to every chain present in the DB so the written file is always a
    complete projection (never drops a chain that wasn't part of the last
    sweep)."""
    if chains is None:
        chains = _db_chains() or list(CHAINS)
    elif isinstance(chains, int):
        chains = [chains]
    out_chains = {}
    latest_ts = None
    for chain in chains:
        markets, chain_ts = _project_chain_markets(chain)
        out_chains[str(chain)] = {"markets": markets}
        if chain_ts:
            latest_ts = max(latest_ts, chain_ts) if latest_ts else chain_ts
    return {
        "generated_at": latest_ts or db.utc_now(),
        "chains": out_chains,
    }


def write_index_json(path=INDEX_PATH, chains=None):
    projection = project_index(chains=chains)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(projection, f, indent=2)
    os.replace(tmp, path)
    return projection


def _sweep_one_chain(client, limiter, chain, errors):
    """Fetch + normalize every active market for one chain. Shares the caller's
    rate limiter so the throttle spans the whole multi-chain budget."""
    limiter.wait()
    active = client.active_markets(chain)
    records = []
    for idx, market in enumerate(active, start=1):
        address = market.get("address")
        if not address:
            errors.append({"chain": chain, "market": None, "error": "active market missing address"})
            continue
        try:
            limiter.wait()
            detail = client.market_detail(chain, address)
            limiter.wait()
            data = client.market_data(chain, address)
            records.append(build_index_record(market, detail, data, chain=chain))
        except (PendleAPIError, KeyError, ValueError) as exc:
            logger.error(f"[Pendle index] chain={chain} {address}: {exc}")
            errors.append({"chain": chain, "market": address, "error": str(exc)})
        if idx % 10 == 0:
            logger.info(f"[Pendle index] chain={chain} fetched {idx}/{len(active)} active markets")
    return active, records


def sweep_index(chains=None, write=True):
    """Sweep all active Pendle markets across the configured chains into SQLite
    and regenerate the merged index feed.

    Chains are swept SEQUENTIALLY behind a single shared RateLimiter — Pendle's
    60 rpm budget is global, so parallel chains would recreate rate-contention.
    """
    if chains is None:
        chains = list(CHAINS)
    elif isinstance(chains, int):
        chains = [chains]

    client = PendleClient()
    limiter = RateLimiter()  # one limiter shared across all chains
    all_records = []
    errors = []
    per_chain = {}

    for chain in chains:
        active, records = _sweep_one_chain(client, limiter, chain, errors)
        per_chain[chain] = {"active": len(active), "records": len(records)}
        all_records.extend(records)
        logger.info(f"[Pendle index] chain={chain} active={len(active)} records={len(records)}")

    projection = None
    if write:
        db.write_records(all_records)
        projection = write_index_json(chains=None)  # project the full DB

    logger.info(
        f"[Pendle index] chains={chains} active={sum(c['active'] for c in per_chain.values())} "
        f"records={len(all_records)} errors={len(errors)} api_calls={limiter.calls} "
        f"rate_interval={limiter.min_interval_sec}s"
    )
    return {
        "chains": chains,
        "per_chain": per_chain,
        "active_markets": sum(c["active"] for c in per_chain.values()),
        "records": len(all_records),
        "errors": errors,
        "api_calls": limiter.calls,
        "projection": projection,
    }


def load_index(path=INDEX_PATH):
    with open(path) as f:
        return json.load(f)


def top_markets(by, n=20, chain=None):
    """Rank indexed markets by `by`. `chain=None` ranks across all chains;
    pass a numeric chain id to scope to one chain."""
    if by not in RANK_FIELDS:
        raise ValueError(f"unsupported rank field {by!r}; expected one of {sorted(RANK_FIELDS)}")
    metric = RANK_FIELDS[by]
    data = load_index()
    all_chains = data.get("chains", {})
    selected = list(all_chains.keys()) if chain is None else [str(chain)]
    rows = []
    for chain_key in selected:
        markets = all_chains.get(chain_key, {}).get("markets", {})
        chain_id = int(chain_key) if chain_key.isdigit() else chain_key
        for address, item in markets.items():
            value = item.get(metric)
            if value is None:
                continue
            rows.append({"market_address": address, "chain": chain_id, **item})
    rows.sort(key=lambda row: row.get(metric), reverse=True)
    return rows[:n]
