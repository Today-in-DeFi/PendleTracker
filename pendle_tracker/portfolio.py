"""Portfolio feed integration for deriving direct Pendle PT watchlist entries."""

import json
import logging
import os
from datetime import datetime, timezone, timedelta

from . import db
from .index import INDEX_PATH, normalize_chain

logger = logging.getLogger(__name__)

DEFAULT_FEED_PATH = "/home/danger/riskAnalyst/data/portfolio/pendle_positions.json"
FEED_MAX_AGE_HOURS = 48
POSITION_SOURCE = "riskAnalyst portfolio feed"


def _parse_time(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _load_feed(path):
    with open(path) as f:
        return json.load(f)


def _feed_timestamp(feed, path):
    generated = _parse_time(feed.get("generated_at"))
    if generated:
        return generated
    try:
        return datetime.fromtimestamp(os.path.getmtime(path), tz=timezone.utc)
    except OSError:
        return None


def _is_stale(feed, path, max_age_hours):
    ts = _feed_timestamp(feed, path)
    if not ts:
        return True
    age = datetime.now(timezone.utc) - ts
    return age > timedelta(hours=max_age_hours)


def _norm_addr(value):
    return str(value or "").strip().lower()


def _chain_id(value):
    """Normalize a feed chain label/id ('eth', 'bsc', 56, ...) to a numeric
    Pendle chain id; None if unknown/missing."""
    return normalize_chain(value)


def _expiry_date(maturity):
    if not maturity:
        return None
    return str(maturity).split("T", 1)[0]


def _load_index_from_json(path=INDEX_PATH):
    try:
        with open(path) as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError) as exc:
        logger.warning(f"[Pendle portfolio] could not read index projection {path}: {exc}")
        return {}

    all_chains = data.get("chains", {})
    out = {}
    for chain_key, chain_block in all_chains.items():
        chain_id = normalize_chain(chain_key)
        if chain_id is None:
            continue
        for market_address, item in chain_block.get("markets", {}).items():
            pt_address = _norm_addr(item.get("pt_address"))
            if not pt_address:
                continue
            # Key on (chain, pt_address): PT token addresses are chain-scoped,
            # never cross-match across chains.
            out[(chain_id, pt_address)] = {
                "market_address": market_address,
                "chain": chain_id,
                **item,
            }
    return out


def _load_index_from_db():
    conn = db.ensure_db()
    try:
        rows = conn.execute(
            """
            SELECT market_address, chain, name, underlier, pt_address, yt_address,
                   sy_address, underlying_address, maturity
            FROM markets
            WHERE pt_address IS NOT NULL
            """
        ).fetchall()
        out = {}
        for row in rows:
            item = dict(row)
            pt_address = _norm_addr(item.get("pt_address"))
            chain_id = normalize_chain(item.get("chain"))
            if not pt_address or chain_id is None:
                continue
            out[(chain_id, pt_address)] = {
                "market_address": item["market_address"],
                "chain": chain_id,
                "name": item.get("name"),
                "underlier": item.get("underlier"),
                "maturity": item.get("maturity"),
                "pt_address": item.get("pt_address"),
                "yt_address": item.get("yt_address"),
                "sy_address": item.get("sy_address"),
                "underlying_address": item.get("underlying_address"),
            }
        return out
    finally:
        conn.close()


def load_pt_index():
    index = _load_index_from_json()
    if index:
        return index
    return _load_index_from_db()


def _market_record_from_index(item):
    return {
        "key": item.get("name"),
        "chain": item.get("chain"),
        "market_address": item["market_address"],
        "underlier": item.get("underlier"),
        "maturity": item.get("maturity"),
        "pt_address": item.get("pt_address"),
        "yt_address": item.get("yt_address"),
        "sy_address": item.get("sy_address"),
        "underlying_address": item.get("underlying_address"),
        "fetched_at": db.utc_now(),
    }


def _write_positions(resolved, ts):
    if not resolved:
        return
    conn = db.ensure_db()
    try:
        with conn:
            for row in resolved:
                db.upsert_market(conn, _market_record_from_index(row["index_item"]), seen_at=ts)
                conn.execute(
                    """
                    INSERT INTO wallets (wallet_address, label, source)
                    VALUES (?, ?, ?)
                    ON CONFLICT(wallet_address) DO UPDATE SET
                      label=excluded.label,
                      source=excluded.source
                    """,
                    (row["wallet_address"], row["wallet_label"], POSITION_SOURCE),
                )
                conn.execute(
                    """
                    INSERT INTO positions (
                      wallet_address, market_address, ts, notional_usd, pt_balance, exposure
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        row["wallet_address"],
                        row["market_address"],
                        ts,
                        row["notional_usd"],
                        row["pt_balance"],
                        "direct",
                    ),
                )
    finally:
        conn.close()


def last_known_direct_watchlist():
    conn = db.ensure_db()
    try:
        latest_ts = conn.execute("SELECT max(ts) FROM positions").fetchone()[0]
        if not latest_ts:
            return []
        rows = conn.execute(
            """
            SELECT p.market_address, SUM(p.notional_usd) AS notional_usd,
                   m.name, m.underlier, m.chain, m.maturity
            FROM positions p
            JOIN markets m ON m.market_address = p.market_address
            WHERE p.ts = ?
            GROUP BY p.market_address
            ORDER BY m.name ASC
            """,
            (latest_ts,),
        ).fetchall()
        return [
            {
                "key": row["name"],
                "market": row["market_address"],
                "chain": row["chain"],
                "underlier": row["underlier"],
                "exposure": "direct",
                "our_notional_usd": row["notional_usd"],
                "expiry": _expiry_date(row["maturity"]),
            }
            for row in rows
        ]
    finally:
        conn.close()


def derive_direct_watchlist(
    feed_path=DEFAULT_FEED_PATH,
    max_age_hours=FEED_MAX_AGE_HOURS,
    write_positions=True,
):
    """Resolve held PT positions to Pendle markets by exact PT-token address."""
    try:
        feed = _load_feed(feed_path)
    except (FileNotFoundError, json.JSONDecodeError, OSError) as exc:
        logger.warning(f"[Pendle portfolio] feed unavailable at {feed_path}: {exc}; using last-known positions")
        return last_known_direct_watchlist()

    if _is_stale(feed, feed_path, max_age_hours):
        logger.warning(f"[Pendle portfolio] feed stale at {feed_path}; using last-known positions")
        return last_known_direct_watchlist()

    index = load_pt_index()
    if not index:
        logger.warning("[Pendle portfolio] no Pendle index available; using last-known positions")
        return last_known_direct_watchlist()

    ts = db.utc_now()
    resolved_rows = []
    by_market = {}

    for pos in feed.get("positions", []):
        chain_id = _chain_id(pos.get("chain"))
        if chain_id is None:
            logger.warning(
                f"[Pendle portfolio] skipping position with unknown chain "
                f"{pos.get('chain')!r}: {pos.get('symbol')}"
            )
            continue
        pt_address = _norm_addr(pos.get("pt_token_address"))
        # Match on (chain, pt_address) — PT token addresses are chain-scoped.
        item = index.get((chain_id, pt_address))
        if not item:
            logger.warning(
                f"[Pendle portfolio] skipping held PT not found in index for chain {chain_id}: "
                f"{pos.get('symbol') or pos.get('position_name')} {pt_address}"
            )
            continue

        market_address = item["market_address"]
        value_usd = pos.get("value_usd") or 0
        resolved_rows.append({
            "wallet_address": pos.get("wallet") or "unknown",
            "wallet_label": pos.get("wallet_label") or pos.get("wallet") or "unknown",
            "market_address": market_address,
            "notional_usd": value_usd,
            "pt_balance": pos.get("pt_balance"),
            "index_item": item,
        })

        current = by_market.setdefault(market_address, {
            "key": item.get("name") or pos.get("symbol") or pos.get("position_name"),
            "market": market_address,
            "chain": chain_id,
            "underlier": item.get("underlier") or pos.get("underlying_slug"),
            "exposure": "direct",
            "our_notional_usd": 0,
            "expiry": _expiry_date(item.get("maturity") or pos.get("maturity")),
        })
        current["our_notional_usd"] += value_usd

    if write_positions:
        _write_positions(resolved_rows, ts)

    if not by_market:
        logger.warning("[Pendle portfolio] no feed positions resolved; using last-known positions")
        return last_known_direct_watchlist()

    logger.info(
        f"[Pendle portfolio] resolved {len(resolved_rows)} positions "
        f"to {len(by_market)} watchlist markets from {feed_path}"
    )
    return list(by_market.values())
