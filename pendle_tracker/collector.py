"""
Pendle collector — builds normalized per-market records, writes the published
snapshot, and appends history.

Public entry points are re-exported from pendle_tracker/__init__.py:
  - snapshot()            run the full watchlist, write snapshot + history
  - get_market(key)       latest record for one market (for in-process analyzer use)
  - query(...)            ad-hoc lookups (used by the CLI)
"""

import json
import logging
import os
from datetime import datetime, timezone

from .client import PendleClient, PendleAPIError
from . import watchlist as wl
from .store import PendleHistoryStore

logger = logging.getLogger(__name__)

_PKG_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_DIR = os.path.dirname(_PKG_DIR)
DATA_DIR = os.path.join(_REPO_DIR, "data")
SNAPSHOT_PATH = os.path.join(DATA_DIR, "pendle_markets.json")
HISTORY_PATH = os.path.join(DATA_DIR, "pendle_markets_history.json")

# Flag thresholds
NEAR_MATURITY_DAYS = 14
LOW_LIQUIDITY_SLIPPAGE_BPS = 50.0   # exit slippage at our notional (or top rung)


def _pct(x):
    """API APYs are fractions (0.12 = 12%); return percent, rounded."""
    return round(x * 100, 4) if x is not None else None


def _days_to_maturity(expiry_iso):
    if not expiry_iso:
        return None
    try:
        exp = datetime.fromisoformat(expiry_iso.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        return None
    delta = exp - datetime.now(timezone.utc)
    return round(delta.total_seconds() / 86400, 2)


def _exit_slippage_ladder(client, entry, pt, underlying):
    """Simulate selling PT -> underlying at each notional; return list of rungs."""
    pt_addr = pt.get("address")
    pt_dec = pt.get("decimals") or 18
    pt_price = (pt.get("price") or {}).get("usd")
    out_addr = underlying.get("address")
    if not (pt_addr and out_addr and pt_price):
        return []

    notionals = set(wl.SLIPPAGE_LADDER_USD)
    if entry.get("our_notional_usd"):
        notionals.add(entry["our_notional_usd"])

    ladder = []
    for usd in sorted(notionals):
        amount_in_raw = int(usd / pt_price * (10 ** pt_dec))
        pi = client.swap_price_impact(
            entry["chain"], entry["market"], pt_addr, out_addr,
            amount_in_raw, wl.SWAP_RECEIVER,
        )
        ladder.append({
            "notional_usd": usd,
            "is_our_notional": usd == entry.get("our_notional_usd"),
            "price_impact_bps": round(abs(pi) * 10000, 3) if pi is not None else None,
        })
    return ladder


def build_market_record(entry, client=None):
    """Fetch + normalize one watchlist market into a full record dict."""
    client = client or PendleClient()
    data = client.market_data(entry["chain"], entry["market"])
    detail = client.market_detail(entry["chain"], entry["market"])

    pt = detail.get("pt") or {}
    yt = detail.get("yt") or {}
    sy = detail.get("sy") or {}
    underlying = detail.get("underlyingAsset") or {}
    expiry = detail.get("expiry")

    pt_implied = _pct(data.get("impliedApy"))
    underlying_apy = _pct(data.get("underlyingApy"))
    spread = (round(pt_implied - underlying_apy, 4)
              if pt_implied is not None and underlying_apy is not None else None)

    ladder = _exit_slippage_ladder(client, entry, pt, underlying)
    our_rung = next((r for r in ladder if r["is_our_notional"]), None)
    slip_at_notional = (our_rung or (ladder[-1] if ladder else {})).get("price_impact_bps")

    days = _days_to_maturity(expiry)
    pt_discount = data.get("ptDiscount")

    record = {
        "key": entry["key"],
        "exposure": entry.get("exposure"),
        "chain": entry["chain"],
        "market_address": entry["market"],
        "underlier": entry.get("underlier"),
        "maturity": expiry,
        "days_to_maturity": days,
        "expired": (days is not None and days <= 0),
        "our_notional_usd": entry.get("our_notional_usd"),

        # addresses
        "pt_address": pt.get("address"),
        "yt_address": yt.get("address"),
        "sy_address": sy.get("address"),
        "underlying_address": underlying.get("address"),

        # yields (percent)
        "pt_implied_apy": pt_implied,
        "underlying_apy": underlying_apy,
        "yt_floating_apy": _pct(data.get("ytFloatingApy")),
        "pt_vs_underlying_spread": spread,
        "aggregated_lp_apy": _pct(data.get("aggregatedApy")),

        # prices (USD)
        "pt_price_usd": (pt.get("price") or {}).get("usd"),
        "yt_price_usd": (yt.get("price") or {}).get("usd"),
        "sy_price_usd": (sy.get("price") or {}).get("usd"),
        "underlying_price_usd": (underlying.get("price") or {}).get("usd"),
        "pt_discount": round(pt_discount * 100, 4) if pt_discount is not None else None,

        # liquidity
        "liquidity_usd": (data.get("liquidity") or {}).get("usd"),
        "total_tvl_usd": (data.get("totalTvl") or {}).get("usd"),
        "trading_volume_usd": (data.get("tradingVolume") or {}).get("usd"),
        "total_pt": data.get("totalPt"),
        "total_sy": data.get("totalSy"),
        "exit_slippage_ladder": ladder,
        "exit_slippage_bps_at_notional": slip_at_notional,

        "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    record["flags"] = _flags(record)
    return record


def _flags(r):
    flags = []
    d = r.get("days_to_maturity")
    if d is not None and 0 < d < NEAR_MATURITY_DAYS:
        flags.append({"code": "near_maturity", "severity": "warning",
                      "msg": f"{d:.1f}d to maturity (<{NEAR_MATURITY_DAYS}d) — roll/exit decision"})
    if r.get("expired"):
        flags.append({"code": "expired", "severity": "warning",
                      "msg": "market past maturity — PT redeemable 1:1, watchlist entry should roll"})
    slip = r.get("exit_slippage_bps_at_notional")
    if slip is not None and slip > LOW_LIQUIDITY_SLIPPAGE_BPS:
        flags.append({"code": "low_liquidity", "severity": "warning",
                      "msg": f"exit slippage {slip:.0f}bps at notional (>{LOW_LIQUIDITY_SLIPPAGE_BPS:.0f}bps)"})
    disc = r.get("pt_discount")
    if disc is not None and disc < 0:
        flags.append({"code": "discount_anomaly", "severity": "info",
                      "msg": f"PT trading above fair (discount {disc:.2f}%)"})
    return flags


def snapshot(write=True):
    """Run the full watchlist; return the snapshot dict. Writes files when write=True."""
    client = PendleClient()
    records, errors = [], []
    for entry in wl.WATCHLIST:
        try:
            records.append(build_market_record(entry, client))
        except (PendleAPIError, KeyError, ValueError) as exc:
            logger.error(f"[Pendle] {entry['key']}: {exc}")
            errors.append({"key": entry["key"], "error": str(exc)})

    snap = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "chain": wl.CHAIN_ID,
        "markets": records,
        "errors": errors,
    }

    if write:
        os.makedirs(DATA_DIR, exist_ok=True)
        tmp = SNAPSHOT_PATH + ".tmp"
        with open(tmp, "w") as f:
            json.dump(snap, f, indent=2)
        os.replace(tmp, SNAPSHOT_PATH)

        store = PendleHistoryStore(HISTORY_PATH)
        for r in records:
            store.append(r["key"], {**r, "timestamp": r["fetched_at"]})
        store.save()
        logger.info(f"[Pendle] snapshot: {len(records)} markets, {len(errors)} errors")

    return snap


def _read_snapshot():
    if not os.path.exists(SNAPSHOT_PATH):
        return None
    with open(SNAPSHOT_PATH) as f:
        return json.load(f)


def _resolve_key(name):
    """Map a caller-supplied name to a watchlist key (exact, then case-insensitive)."""
    if not name:
        return None
    for e in wl.WATCHLIST:
        if e["key"] == name:
            return e["key"]
    low = name.lower()
    for e in wl.WATCHLIST:
        if e["key"].lower() == low:
            return e["key"]
    return None


def get_market(key, live=False):
    """
    Return the latest record for one market.

    Default reads the published snapshot (cheap; decouples analyzer runtime from
    the API). live=True fetches fresh from the API. Key match is case-insensitive.
    """
    resolved = _resolve_key(key) or key
    if live:
        entry = wl.get_entry(resolved)
        if not entry:
            return None
        return build_market_record(entry)
    snap = _read_snapshot()
    if not snap:
        return None
    return next((m for m in snap.get("markets", []) if m["key"] == resolved), None)


def query(key=None, field=None, live=False):
    """Ad-hoc lookup helper for the CLI. Returns a record, a field value, or all."""
    if key:
        rec = get_market(key, live=live)
        if rec and field:
            return rec.get(field)
        return rec
    snap = _read_snapshot() if not live else snapshot(write=False)
    return snap.get("markets", []) if snap else []


def _age_hours(rec):
    ts = rec.get("fetched_at")
    if not ts:
        return None
    try:
        when = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        return None
    return round((datetime.now(timezone.utc) - when).total_seconds() / 3600, 2)


def get_position_enrichment(position_name, live=False, max_age_hours=None):
    """
    Stable consumption contract for portfolio digests (e.g. FarmTracker).

    Given a portfolio PT position's name (e.g. "PT-srUSDat-27AUG2026"), return a
    flat dict of the Pendle metrics a digest wants, or None if the name is not in
    our watchlist. Reads the published snapshot by default (cheap); live=True
    re-fetches from the API.

    Keys are intentionally digest-friendly and decoupled from internal record
    field names, so FarmTracker can depend on this shape without tracking our
    snapshot schema.

    `max_age_hours`: if set and the snapshot record is older, returns the data but
    with stale=True so the caller can decide whether to show it.
    """
    rec = get_market(position_name, live=live)
    if not rec:
        return None
    age = _age_hours(rec)
    return {
        "key": rec["key"],
        "matched": True,
        "age_hours": age,
        "stale": (max_age_hours is not None and age is not None and age > max_age_hours),
        "fetched_at": rec.get("fetched_at"),

        "maturity": rec.get("maturity"),
        "days_to_maturity": rec.get("days_to_maturity"),
        "expired": rec.get("expired"),

        "fixed_apy": rec.get("pt_implied_apy"),          # YTM, Pendle-canonical (percent)
        "underlying_apy": rec.get("underlying_apy"),     # percent
        "spread_vs_underlying": rec.get("pt_vs_underlying_spread"),

        "pt_price_usd": rec.get("pt_price_usd"),
        "pt_discount": rec.get("pt_discount"),           # percent

        "liquidity_usd": rec.get("liquidity_usd"),
        "our_notional_usd": rec.get("our_notional_usd"),
        "exit_slippage_bps_at_notional": rec.get("exit_slippage_bps_at_notional"),
        "exit_slippage_ladder": rec.get("exit_slippage_ladder"),

        "flags": rec.get("flags", []),
    }


def format_pt_summary(enr):
    """
    Optional convenience: a compact one-liner for a PT position. Consumers with
    their own formatting (FarmTracker) can ignore this and read fields directly.

    e.g. "fixed 12.1% APY · 62d to maturity · exit $53k ~5bps"
    """
    if not enr:
        return ""
    parts = []
    if enr.get("fixed_apy") is not None:
        parts.append(f"fixed {enr['fixed_apy']:.1f}% APY")
    d = enr.get("days_to_maturity")
    if d is not None:
        warn = " ⚠️" if any(f["code"] == "near_maturity" for f in enr.get("flags", [])) else ""
        parts.append(f"{d:.0f}d to maturity{warn}")
    slip = enr.get("exit_slippage_bps_at_notional")
    notional = enr.get("our_notional_usd")
    if slip is not None and notional:
        parts.append(f"exit ${notional/1000:.0f}k ~{slip:.0f}bps")
    return " · ".join(parts)
