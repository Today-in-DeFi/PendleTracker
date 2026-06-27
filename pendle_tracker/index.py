"""Broad Ethereum Pendle market index and ranking helpers."""

import json
import logging
import os
import time
from datetime import datetime, timezone

from .client import PendleClient, PendleAPIError
from . import db
from .collector import compute_yt_analytics, compute_lp_analytics

logger = logging.getLogger(__name__)

CHAIN_ID = 1
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


def build_index_record(active_entry, detail, data=None):
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
        "chain": detail.get("chainId") or CHAIN_ID,
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


def _latest_index_rows(chain=CHAIN_ID):
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


def project_index(chain=CHAIN_ID):
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
    return {
        "generated_at": latest_ts or db.utc_now(),
        "chains": {
            str(chain): {
                "markets": markets,
            }
        },
    }


def write_index_json(path=INDEX_PATH, chain=CHAIN_ID):
    projection = project_index(chain=chain)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(projection, f, indent=2)
    os.replace(tmp, path)
    return projection


def sweep_index(chain=CHAIN_ID, write=True):
    """Sweep all active Ethereum markets into SQLite and regenerate the index feed."""
    if chain != CHAIN_ID:
        raise ValueError("P1-B only supports Ethereum mainnet chain=1")

    client = PendleClient()
    limiter = RateLimiter()
    limiter.wait()
    active = client.active_markets(chain)
    records = []
    errors = []

    for idx, market in enumerate(active, start=1):
        address = market.get("address")
        if not address:
            errors.append({"market": None, "error": "active market missing address"})
            continue
        try:
            limiter.wait()
            detail = client.market_detail(chain, address)
            limiter.wait()
            data = client.market_data(chain, address)
            records.append(build_index_record(market, detail, data))
        except (PendleAPIError, KeyError, ValueError) as exc:
            logger.error(f"[Pendle index] {address}: {exc}")
            errors.append({"market": address, "error": str(exc)})
        if idx % 10 == 0:
            logger.info(f"[Pendle index] fetched {idx}/{len(active)} active markets")

    projection = None
    if write:
        db.write_records(records)
        projection = write_index_json(chain=chain)

    logger.info(
        f"[Pendle index] active={len(active)} records={len(records)} "
        f"errors={len(errors)} api_calls={limiter.calls} rate_interval={limiter.min_interval_sec}s"
    )
    return {
        "active_markets": len(active),
        "records": len(records),
        "errors": errors,
        "api_calls": limiter.calls,
        "projection": projection,
    }


def load_index(path=INDEX_PATH):
    with open(path) as f:
        return json.load(f)


def top_markets(by, n=20, chain=CHAIN_ID):
    if by not in RANK_FIELDS:
        raise ValueError(f"unsupported rank field {by!r}; expected one of {sorted(RANK_FIELDS)}")
    metric = RANK_FIELDS[by]
    data = load_index()
    markets = data.get("chains", {}).get(str(chain), {}).get("markets", {})
    rows = []
    for address, item in markets.items():
        value = item.get(metric)
        if value is None:
            continue
        rows.append({"market_address": address, **item})
    rows.sort(key=lambda row: row.get(metric), reverse=True)
    return rows[:n]
