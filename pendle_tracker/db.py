"""SQLite storage and JSON projection helpers for PendleTracker."""

import json
import os
import sqlite3
from datetime import datetime, timezone, timedelta

from . import watchlist as wl

_PKG_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_DIR = os.path.dirname(_PKG_DIR)
DATA_DIR = os.path.join(_REPO_DIR, "data")
DB_PATH = os.path.join(DATA_DIR, "pendle.db")

SNAPSHOT_COLUMNS = [
    "pt_implied_apy",
    "underlying_apy",
    "yt_floating_apy",
    "aggregated_lp_apy",
    "pt_vs_underlying_spread",
    "pt_price_usd",
    "yt_price_usd",
    "sy_price_usd",
    "underlying_price_usd",
    "pt_discount",
    "liquidity_usd",
    "total_tvl_usd",
    "trading_volume_usd",
    "total_pt",
    "total_sy",
    "days_to_maturity",
    "exit_slippage_bps_at_notional",
]

HISTORY_IMPORT_FIELDS = [
    "pt_price_usd",
    "underlying_price_usd",
    "pt_implied_apy",
    "underlying_apy",
    "pt_vs_underlying_spread",
    "yt_floating_apy",
    "pt_discount",
    "liquidity_usd",
    "total_tvl_usd",
    "days_to_maturity",
    "exit_slippage_bps_at_notional",
]


def utc_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def connect(db_path=DB_PATH):
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn):
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS markets (
          market_address TEXT PRIMARY KEY,
          chain INTEGER, name TEXT, underlier TEXT,
          pt_address TEXT, yt_address TEXT, sy_address TEXT, underlying_address TEXT,
          maturity TEXT, first_seen TEXT, last_seen TEXT
        );
        CREATE TABLE IF NOT EXISTS market_snapshots (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          market_address TEXT NOT NULL REFERENCES markets(market_address),
          ts TEXT NOT NULL,
          pt_implied_apy REAL, underlying_apy REAL, yt_floating_apy REAL, aggregated_lp_apy REAL,
          pt_vs_underlying_spread REAL,
          pt_price_usd REAL, yt_price_usd REAL, sy_price_usd REAL, underlying_price_usd REAL,
          pt_discount REAL,
          liquidity_usd REAL, total_tvl_usd REAL, trading_volume_usd REAL,
          total_pt REAL, total_sy REAL,
          days_to_maturity REAL, expired INTEGER,
          exit_slippage_bps_at_notional REAL,
          price_source TEXT,
          exit_slippage_ladder_json TEXT
        );
        CREATE INDEX IF NOT EXISTS ix_msnap_market_ts ON market_snapshots(market_address, ts);
        CREATE TABLE IF NOT EXISTS wallets (
          wallet_address TEXT PRIMARY KEY, label TEXT, source TEXT
        );
        CREATE TABLE IF NOT EXISTS positions (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          wallet_address TEXT NOT NULL REFERENCES wallets(wallet_address),
          market_address TEXT NOT NULL REFERENCES markets(market_address),
          ts TEXT NOT NULL,
          notional_usd REAL, pt_balance REAL, exposure TEXT
        );
        CREATE INDEX IF NOT EXISTS ix_pos_wallet_ts ON positions(wallet_address, ts);
        CREATE INDEX IF NOT EXISTS ix_pos_market_ts ON positions(market_address, ts);
        """
    )


def ensure_db(db_path=DB_PATH):
    conn = connect(db_path)
    init_db(conn)
    return conn


def _entry_by_key(key):
    return wl.get_entry(key)


def _entry_by_market(address):
    low = (address or "").lower()
    for entry in wl.WATCHLIST:
        if entry["market"].lower() == low:
            return entry
    return None


def upsert_market(conn, record, seen_at=None):
    seen_at = seen_at or record.get("fetched_at") or utc_now()
    conn.execute(
        """
        INSERT INTO markets (
          market_address, chain, name, underlier,
          pt_address, yt_address, sy_address, underlying_address,
          maturity, first_seen, last_seen
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(market_address) DO UPDATE SET
          chain=excluded.chain,
          name=excluded.name,
          underlier=excluded.underlier,
          pt_address=COALESCE(excluded.pt_address, markets.pt_address),
          yt_address=COALESCE(excluded.yt_address, markets.yt_address),
          sy_address=COALESCE(excluded.sy_address, markets.sy_address),
          underlying_address=COALESCE(excluded.underlying_address, markets.underlying_address),
          maturity=COALESCE(excluded.maturity, markets.maturity),
          last_seen=excluded.last_seen
        """,
        (
            record["market_address"],
            record.get("chain"),
            record.get("key"),
            record.get("underlier"),
            record.get("pt_address"),
            record.get("yt_address"),
            record.get("sy_address"),
            record.get("underlying_address"),
            record.get("maturity"),
            seen_at,
            seen_at,
        ),
    )


def insert_market_snapshot(conn, record, price_source="pendle_api"):
    values = [record.get(col) for col in SNAPSHOT_COLUMNS]
    conn.execute(
        f"""
        INSERT INTO market_snapshots (
          market_address, ts,
          {", ".join(SNAPSHOT_COLUMNS)},
          expired, price_source, exit_slippage_ladder_json
        )
        VALUES (
          ?, ?,
          {", ".join("?" for _ in SNAPSHOT_COLUMNS)},
          ?, ?, ?
        )
        """,
        [
            record["market_address"],
            record.get("fetched_at") or record.get("timestamp") or utc_now(),
            *values,
            1 if record.get("expired") else 0,
            price_source,
            json.dumps(record.get("exit_slippage_ladder") or []),
        ],
    )


def write_records(records, db_path=DB_PATH):
    conn = ensure_db(db_path)
    try:
        with conn:
            for record in records:
                upsert_market(conn, record)
                insert_market_snapshot(conn, record)
    finally:
        conn.close()


def _load_snapshot_records(snapshot_path):
    try:
        with open(snapshot_path) as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return {m.get("key"): m for m in data.get("markets", []) if m.get("key")}


def import_history_json(history_path, snapshot_path, db_path=DB_PATH):
    """One-time import of the retired JSON history file into SQLite."""
    if not os.path.exists(history_path):
        return 0

    conn = ensure_db(db_path)
    try:
        existing = conn.execute("SELECT count(*) FROM market_snapshots").fetchone()[0]
        if existing:
            return 0

        try:
            with open(history_path) as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            return 0

        latest_records = _load_snapshot_records(snapshot_path)
        imported = 0
        with conn:
            for key, bucket in (data.get("markets") or {}).items():
                entry = _entry_by_key(key)
                if not entry:
                    continue
                dimension = dict(latest_records.get(key) or {})
                dimension.update({
                    "key": key,
                    "market_address": entry["market"],
                    "chain": entry["chain"],
                    "underlier": entry.get("underlier"),
                    "maturity": dimension.get("maturity") or entry.get("expiry"),
                })
                for point in bucket.get("entries", []):
                    ts = point.get("timestamp") or point.get("ts")
                    if not ts:
                        continue
                    record = dict(dimension)
                    for field in HISTORY_IMPORT_FIELDS:
                        record[field] = point.get(field)
                    record["fetched_at"] = ts
                    record["expired"] = point.get("expired") or False
                    record["exit_slippage_ladder"] = point.get("exit_slippage_ladder") or []
                    upsert_market(conn, record, seen_at=ts)
                    duplicate = conn.execute(
                        """
                        SELECT 1 FROM market_snapshots
                        WHERE market_address = ? AND ts = ?
                        LIMIT 1
                        """,
                        (record["market_address"], ts),
                    ).fetchone()
                    if duplicate:
                        continue
                    insert_market_snapshot(conn, record)
                    imported += 1
        return imported
    finally:
        conn.close()


def _latest_snapshot_row(conn, market_address):
    return conn.execute(
        """
        SELECT * FROM market_snapshots
        WHERE market_address = ?
        ORDER BY ts DESC, id DESC
        LIMIT 1
        """,
        (market_address,),
    ).fetchone()


def _latest_position_row(conn, market_address):
    return conn.execute(
        """
        SELECT * FROM positions
        WHERE market_address = ?
        ORDER BY ts DESC, id DESC
        LIMIT 1
        """,
        (market_address,),
    ).fetchone()


def _market_row(conn, market_address):
    return conn.execute(
        "SELECT * FROM markets WHERE market_address = ?",
        (market_address,),
    ).fetchone()


def project_snapshot(errors=None, flag_func=None, db_path=DB_PATH):
    """Build the published JSON feed from latest DB rows."""
    conn = ensure_db(db_path)
    try:
        markets = []
        latest_ts = None
        for entry in wl.WATCHLIST:
            market_address = entry["market"]
            market = _market_row(conn, market_address)
            snap = _latest_snapshot_row(conn, market_address)
            if not market or not snap:
                continue
            pos = _latest_position_row(conn, market_address)
            notional = pos["notional_usd"] if pos and pos["notional_usd"] is not None else entry.get("our_notional_usd")
            exposure = pos["exposure"] if pos and pos["exposure"] is not None else entry.get("exposure")
            ladder = json.loads(snap["exit_slippage_ladder_json"] or "[]")
            rec = {
                "key": market["name"],
                "exposure": exposure,
                "chain": market["chain"],
                "market_address": market["market_address"],
                "underlier": market["underlier"],
                "maturity": market["maturity"],
                "days_to_maturity": snap["days_to_maturity"],
                "expired": bool(snap["expired"]),
                "our_notional_usd": notional,
                "pt_address": market["pt_address"],
                "yt_address": market["yt_address"],
                "sy_address": market["sy_address"],
                "underlying_address": market["underlying_address"],
                "pt_implied_apy": snap["pt_implied_apy"],
                "underlying_apy": snap["underlying_apy"],
                "yt_floating_apy": snap["yt_floating_apy"],
                "pt_vs_underlying_spread": snap["pt_vs_underlying_spread"],
                "aggregated_lp_apy": snap["aggregated_lp_apy"],
                "pt_price_usd": snap["pt_price_usd"],
                "yt_price_usd": snap["yt_price_usd"],
                "sy_price_usd": snap["sy_price_usd"],
                "underlying_price_usd": snap["underlying_price_usd"],
                "pt_discount": snap["pt_discount"],
                "liquidity_usd": snap["liquidity_usd"],
                "total_tvl_usd": snap["total_tvl_usd"],
                "trading_volume_usd": snap["trading_volume_usd"],
                "total_pt": snap["total_pt"],
                "total_sy": snap["total_sy"],
                "exit_slippage_ladder": ladder,
                "exit_slippage_bps_at_notional": snap["exit_slippage_bps_at_notional"],
                "fetched_at": snap["ts"],
            }
            rec["flags"] = flag_func(rec) if flag_func else []
            markets.append(rec)
            latest_ts = max(latest_ts, snap["ts"]) if latest_ts else snap["ts"]
        return {
            "generated_at": latest_ts or utc_now(),
            "chain": wl.CHAIN_ID,
            "markets": markets,
            "errors": errors or [],
        }
    finally:
        conn.close()


def write_snapshot_json(snapshot_path, errors=None, flag_func=None, db_path=DB_PATH):
    snap = project_snapshot(errors=errors, flag_func=flag_func, db_path=db_path)
    os.makedirs(os.path.dirname(snapshot_path), exist_ok=True)
    tmp = snapshot_path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(snap, f, indent=2)
    os.replace(tmp, snapshot_path)
    return snap


def history(market, days=None, db_path=DB_PATH):
    """Return market snapshot rows ordered by ts for a watchlist key or address."""
    conn = ensure_db(db_path)
    try:
        entry = _entry_by_key(market) or _entry_by_market(market)
        market_address = entry["market"] if entry else market
        params = [market_address]
        where = "market_address = ?"
        if days is not None:
            cutoff = datetime.now(timezone.utc) - timedelta(days=days)
            where += " AND ts >= ?"
            params.append(cutoff.strftime("%Y-%m-%dT%H:%M:%SZ"))
        rows = conn.execute(
            f"""
            SELECT * FROM market_snapshots
            WHERE {where}
            ORDER BY ts ASC, id ASC
            """,
            params,
        ).fetchall()
        out = []
        for row in rows:
            item = dict(row)
            item["expired"] = bool(item.get("expired"))
            item["timestamp"] = item["ts"]
            try:
                item["exit_slippage_ladder"] = json.loads(item.pop("exit_slippage_ladder_json") or "[]")
            except json.JSONDecodeError:
                item["exit_slippage_ladder"] = []
            out.append(item)
        return out
    finally:
        conn.close()
