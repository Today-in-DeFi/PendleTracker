#!/usr/bin/env python3
"""
Pendle positions digest — by wallet.

A scheduled summary (sibling to FarmTracker / DexTracker daily digests) of the
Pendle PT positions we actually hold, organised by wallet. Distinct from
pendle_risk_alerter.py, which is event/transition-driven; this just renders the
current state on a cadence and posts it to the "TID Pendle Tracking" channel.

Two inputs, joined on (chain, pt_address):

  1. HOLDINGS  — riskAnalyst portfolio feed pendle_positions.json. Authoritative
     list of held PTs across every wallet, with per-position wallet attribution
     (wallet / wallet_label), value_usd, entry_value, days_held, maturity, chain.

  2. INTEL     — our own data/pendle_markets.json (written by `pendle_tracker
     snapshot`): fixed APY, PT discount, exit-slippage bps at our notional, and
     risk flags (near_maturity, low_liquidity, composition_drift, yt_underwater,
     expired).

The feed drives grouping; the snapshot enriches each line. If a held PT has no
matching snapshot record we still show it from feed fields alone.

Stdlib only. Telegram send modelled on pendle_risk_alerter.send_telegram, with
4096-char chunking added. Creds in telegram_config.json under `pendle_reporter`.

Usage:
    python3 pendle_digest.py             # render + send
    python3 pendle_digest.py --print     # render to stdout, do not send
    python3 pendle_digest.py --dry-run   # alias for --print
"""

import argparse
import html
import json
import os
import sys
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
from urllib.parse import urlencode

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(PROJECT_DIR, "data")
TELEGRAM_CONFIG = os.path.join(PROJECT_DIR, "telegram_config.json")
SNAPSHOT_PATH = os.path.join(DATA_DIR, "pendle_markets.json")
FEED_PATH = "/home/danger/riskAnalyst/data/portfolio/pendle_positions.json"

CONFIG_SECTION = "pendle_reporter"
FETCH_TIMEOUT = 15
TELEGRAM_MAX_CHARS = 4096

# Freshness guards: banner the digest rather than withhold positions.
SNAPSHOT_STALE_HOURS = 6     # data/pendle_markets.json cadence is hourly
FEED_STALE_HOURS = 48        # riskAnalyst sync cadence

# chain id -> short tag shown after a position name (ETH stays implicit)
CHAIN_TAG = {56: "BNB", 42161: "ARB", 137: "POLY", 10: "OP", 8453: "BASE"}
CHAIN_ALIASES = {
    "eth": 1, "ethereum": 1, "mainnet": 1, "1": 1,
    "bsc": 56, "bnb": 56, "binance": 56, "56": 56,
    "arbitrum": 42161, "arb": 42161, "42161": 42161,
}


# --------------------------------------------------------------------------- #
# loading
# --------------------------------------------------------------------------- #

def _parse_ts(ts):
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
    if dt.tzinfo is None:           # bare dates (entry_date) -> assume UTC
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _age_hours(ts_str, now):
    ts = _parse_ts(ts_str)
    if ts is None:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return (now - ts).total_seconds() / 3600


def _chain_id(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    return CHAIN_ALIASES.get(str(value).strip().lower())


def _norm_addr(value):
    return str(value or "").strip().lower()


def load_json(path):
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError) as exc:
        print(f"WARN: could not read {path}: {exc}", file=sys.stderr)
        return None


def index_markets(snapshot):
    """Map (chain_id, pt_address) -> market record from pendle_markets.json."""
    out = {}
    if not snapshot:
        return out
    for m in snapshot.get("markets", []):
        cid = _chain_id(m.get("chain"))
        pt = _norm_addr(m.get("pt_address"))
        if cid is None or not pt:
            continue
        out[(cid, pt)] = m
    return out


# --------------------------------------------------------------------------- #
# formatting helpers
# --------------------------------------------------------------------------- #

def _esc(s):
    return html.escape(str(s), quote=False) if s is not None else ""


def fmt_usd(v):
    if v is None:
        return "$?"
    a = abs(v)
    sign = "-" if v < 0 else ""
    if a >= 1_000_000:
        s = f"{a/1_000_000:.2f}M".replace(".00M", "M")
    elif a >= 1_000:
        s = f"{a/1_000:.1f}K".replace(".0K", "K")
    else:
        return f"{sign}${a:,.0f}"
    return f"{sign}${s}"


def fmt_pct(v):
    return f"{v:.1f}%" if v is not None else "?"


# --------------------------------------------------------------------------- #
# position assembly
# --------------------------------------------------------------------------- #

FLAG_LABEL = {
    "near_maturity": "⚠️ near maturity",
    "expired": "🚨 expired",
    "low_liquidity": "💧 low liquidity",
    "composition_drift": "↔ composition drift",
    "discount_anomaly": "❗ discount anomaly",
    "yt_underwater": "🌊 YT underwater",
}


def _sane(v, floor=-99.0):
    """The Pendle API returns 0/-100 sentinels when an underlying/YT feed is
    missing; treat those as 'no data' so we don't render garbage yields."""
    return v is not None and v > floor


def apy_trend(market_key, entry_date, current_apy, now):
    """Reference implied APY for context: the value at (nearest to) entry when
    our DB history brackets entry_date, else the oldest tracked point with an
    honest horizon label. Returns {ref_apy, label, delta_pp} or None."""
    try:
        from pendle_tracker import history
        rows = history(market_key)
    except Exception:                                   # noqa: BLE001 - never break the digest
        return None
    pts = []
    for r in rows:
        a, t = r.get("pt_implied_apy"), _parse_ts(r.get("ts") or r.get("timestamp"))
        if a is not None and t is not None:
            pts.append((t, a))
    if not pts:
        return None
    pts.sort()
    entry_dt = _parse_ts(entry_date)
    oldest_t = pts[0][0]
    if entry_dt and oldest_t <= entry_dt <= now:
        ref_a = min(pts, key=lambda p: abs((p[0] - entry_dt).total_seconds()))[1]
        label = "entry"
    else:
        ref_a = pts[0][1]
        d = max(0, (now - oldest_t).days)
        label = f"{d}d ago" if d > 0 else "since tracked"
    delta = (current_apy - ref_a) if current_apy is not None else None
    return {"ref_apy": ref_a, "label": label, "delta_pp": delta}


def build_position(pos, market_index, now):
    """Merge a feed position with its snapshot record into a flat render dict."""
    cid = _chain_id(pos.get("chain"))
    pt = _norm_addr(pos.get("pt_token_address"))
    rec = market_index.get((cid, pt)) or {}

    # fixed APY: prefer snapshot (percent); fall back to feed fraction.
    fixed = rec.get("pt_implied_apy")
    if fixed is None and pos.get("pt_implied_apy") is not None:
        fixed = pos["pt_implied_apy"] * 100.0

    name = rec.get("key") or pos.get("symbol") or pos.get("position_name") or "?"
    flags = [f.get("code") for f in rec.get("flags", []) if f.get("code")]

    value_usd = pos.get("value_usd") or 0.0
    entry_value = pos.get("entry_value")
    pnl_usd = (value_usd - entry_value) if entry_value else None
    pnl_pct = (pnl_usd / entry_value * 100) if entry_value else None

    # deepest ladder rung (largest notional) as an exit-depth indicator
    ladder = rec.get("exit_slippage_ladder") or []
    deep = max(ladder, key=lambda r: r.get("notional_usd") or 0, default=None)

    # entry-vs-current rate context. Prefer FarmTracker's captured locked entry
    # APY (carried on the feed); fall back to our own DB history for positions
    # that predate entry_apy capture.
    trend = None
    entry_apy_frac = pos.get("entry_apy")
    if entry_apy_frac is not None and fixed is not None:
        entry_apy = entry_apy_frac * 100.0
        trend = {"ref_apy": entry_apy, "label": "entry", "delta_pp": fixed - entry_apy}
    elif rec:
        trend = apy_trend(name, pos.get("entry_date"), fixed, now)

    return {
        "name": name,
        "chain_tag": CHAIN_TAG.get(cid),
        "value_usd": value_usd,
        "fixed_apy": fixed,
        "apy_trend": trend,
        "days_to_maturity": rec.get("days_to_maturity"),
        "days_held": pos.get("days_held"),
        # mark-to-market
        "pt_price_usd": rec.get("pt_price_usd"),
        "underlying_price_usd": rec.get("underlying_price_usd"),
        "pt_discount": rec.get("pt_discount"),
        "pnl_usd": pnl_usd,
        "pnl_pct": pnl_pct,
        # pool / exit liquidity
        "liquidity_usd": rec.get("liquidity_usd"),
        "total_tvl_usd": rec.get("total_tvl_usd"),
        "pt_sy_ratio": rec.get("pt_sy_ratio"),
        "aggregated_lp_apy": rec.get("aggregated_lp_apy"),
        "exit_bps": rec.get("exit_slippage_bps_at_notional"),
        "exit_deep_bps": (deep or {}).get("price_impact_bps") if deep else None,
        "exit_deep_usd": (deep or {}).get("notional_usd") if deep else None,
        # yield decomposition (PT vs underlying vs YT)
        "underlying_apy": rec.get("underlying_apy"),
        "yt_floating_apy": rec.get("yt_floating_apy"),
        "yt_price_usd": rec.get("yt_price_usd"),
        "pt_vs_underlying_spread": rec.get("pt_vs_underlying_spread"),
        "flags": flags,
        "matched": bool(rec),
    }


def group_by_wallet(feed, market_index, now):
    wallets = {}
    for pos in feed.get("positions", []):
        label = pos.get("wallet_label") or pos.get("wallet") or "Unknown"
        wallets.setdefault(label, []).append(build_position(pos, market_index, now))
    # sort positions within each wallet by value desc
    for label in wallets:
        wallets[label].sort(key=lambda p: p["value_usd"], reverse=True)
    # order wallets by total value desc
    return sorted(
        wallets.items(),
        key=lambda kv: sum(p["value_usd"] for p in kv[1]),
        reverse=True,
    )


# --------------------------------------------------------------------------- #
# render
# --------------------------------------------------------------------------- #

def _signed_pp(v):
    return f"{'+' if v >= 0 else '−'}{abs(v):.1f}pp"


def _status_emoji(p):
    if "expired" in p["flags"]:
        return "🔴"
    return "⚠️" if p["flags"] else "🟢"


def render_glance(p):
    """The always-visible triage layer: ONE readable line per position —
    name · size · fixed APY (with a direction arrow vs entry) · days · P&L%.
    Everything else lives in the per-wallet expandable detail block."""
    name = _esc(p["name"])
    if p["chain_tag"]:
        name += f" <i>({p['chain_tag']})</i>"
    parts = [f"{_status_emoji(p)} <b>{name}</b>", fmt_usd(p["value_usd"])]

    if p["fixed_apy"] is not None:
        arrow = ""
        tr = p["apy_trend"]
        if tr and tr["delta_pp"] is not None:
            arrow = "▲" if tr["delta_pp"] > 0.05 else "▼" if tr["delta_pp"] < -0.05 else ""
        parts.append(f"{fmt_pct(p['fixed_apy'])}{arrow}")
    if p["days_to_maturity"] is not None:
        warn = " ⚠️" if "near_maturity" in p["flags"] else ""
        parts.append(f"{p['days_to_maturity']:.0f}d{warn}")
    if not p["matched"]:
        parts.append("<i>feed only</i>")
    elif p["pnl_usd"] is not None and abs(p["pnl_pct"]) >= 0.5:
        s = "+" if p["pnl_usd"] >= 0 else "−"
        parts.append(f"P&L {s}{abs(p['pnl_pct']):.0f}%")
    return " · ".join(parts)


def render_detail(p, show_name):
    """The diligence layer (inside the per-wallet expandable block): the rate
    move vs entry, P&L, exit liquidity, pool depth, marks, and yield split."""
    if not p["matched"]:
        return []
    rows = []

    # rate now vs entry — the headline detail
    if p["fixed_apy"] is not None:
        s = f"rate {fmt_pct(p['fixed_apy'])} now"
        tr = p["apy_trend"]
        if tr and tr["ref_apy"] is not None and tr["delta_pp"] is not None:
            arrow = "▲" if tr["delta_pp"] > 0.05 else "▼" if tr["delta_pp"] < -0.05 else "→"
            s += f" · {fmt_pct(tr['ref_apy'])} at {tr['label']} ({arrow}{abs(tr['delta_pp']):.1f}pp)"
        rows.append(s)

    # money: P&L vs entry + underlying price
    money = []
    if p["pnl_usd"] is not None:
        if abs(p["pnl_pct"]) < 0.5:
            money.append("P&L flat")
        else:
            s = "+" if p["pnl_usd"] >= 0 else "−"
            money.append(f"P&L {s}{fmt_usd(abs(p['pnl_usd']))} ({s}{abs(p['pnl_pct']):.0f}%)")
    if p["underlying_price_usd"] is not None:
        money.append(f"underlying ${p['underlying_price_usd']:.3f}")
    if money:
        rows.append(" · ".join(money))

    # exit liquidity (how trapped we are, at our size)
    exit_line = []
    if p["exit_bps"] is not None:
        e = f"exit ~{p['exit_bps']:.0f}bps at our size"
        if p["exit_deep_bps"] is not None and p["exit_deep_usd"]:
            e += f" (→{p['exit_deep_bps']:.0f}bps @{fmt_usd(p['exit_deep_usd'])})"
        exit_line.append(e)
    if p["liquidity_usd"] is not None:
        exit_line.append(f"liq {fmt_usd(p['liquidity_usd'])}")
    if exit_line:
        rows.append(" · ".join(exit_line))

    # pool depth / composition (its own line)
    pool = []
    if p["total_tvl_usd"] is not None:
        pool.append(f"TVL {fmt_usd(p['total_tvl_usd'])}")
    if p["pt_sy_ratio"] is not None:
        drift = " ↔drift" if "composition_drift" in p["flags"] else ""
        pool.append(f"PT/SY {p['pt_sy_ratio']:.2f}{drift}")
    if pool:
        rows.append(" · ".join(pool))

    # marks + yield split
    mk = []
    if p["pt_price_usd"] is not None:
        mk.append(f"PT ${p['pt_price_usd']:.4f}")
    if p["yt_price_usd"] is not None:
        mk.append(f"YT ${p['yt_price_usd']:.4f}")
    if p["pt_discount"] is not None:
        mk.append(f"disc {fmt_pct(p['pt_discount'])}")
    if _sane(p["underlying_apy"], 0.0):
        mk.append(f"spot {fmt_pct(p['underlying_apy'])}")
        if p["pt_vs_underlying_spread"] is not None:
            mk.append(f"PT vs spot {_signed_pp(p['pt_vs_underlying_spread'])}")
    if mk:
        rows.append(" · ".join(mk))

    extra = [FLAG_LABEL.get(c, c) for c in p["flags"]
             if c not in {"near_maturity", "composition_drift"}]
    if extra:
        rows.append(" · ".join(extra))

    if not rows:
        return []
    # Only label the block with the PT name when a wallet has >1 position (where
    # it disambiguates); for a single position it just repeats the glance line.
    if show_name:
        return [f"<b>{_esc(p['name'])}</b>"] + [f"  {r}" for r in rows]
    return rows


def render_digest(feed, market_index, now, snapshot_age_h, feed_age_h):
    wallets = group_by_wallet(feed, market_index, now)

    date_str = now.strftime("%Y-%m-%d")
    lines = [f"🟣 <b>TID Pendle Digest</b> — {date_str}"]

    # freshness banners
    if snapshot_age_h is not None and snapshot_age_h > SNAPSHOT_STALE_HOURS:
        lines.append(f"⚠️ <i>market intel {snapshot_age_h:.0f}h stale</i>")
    if feed_age_h is not None and feed_age_h > FEED_STALE_HOURS:
        lines.append(f"⚠️ <i>holdings feed {feed_age_h:.0f}h stale</i>")

    for label, positions in wallets:
        lines.append(f"\n👛 <b>{_esc(label)}</b>")
        for p in positions:
            lines.append(render_glance(p))
        # collapsed diligence block for this wallet (tap to expand). Name each
        # position only when the wallet holds more than one.
        multi = len(positions) > 1
        detail = []
        for p in positions:
            detail.extend(render_detail(p, show_name=multi))
        if detail:
            lines.append("<blockquote expandable>" + "\n".join(detail) + "</blockquote>")

    lines.append(f"\n<i>source: pendle_markets.json + riskAnalyst feed</i>")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# telegram
# --------------------------------------------------------------------------- #

def load_telegram_creds():
    cfg = load_json(TELEGRAM_CONFIG) or {}
    tg = cfg.get(CONFIG_SECTION, {}).get("telegram", {})
    return tg.get("bot_token"), tg.get("chat_id")


def _chunk(text, limit=TELEGRAM_MAX_CHARS):
    """Split on line boundaries so no message exceeds Telegram's limit."""
    if len(text) <= limit:
        return [text]
    chunks, cur = [], ""
    for line in text.split("\n"):
        if cur and len(cur) + 1 + len(line) > limit:
            chunks.append(cur)
            cur = line
        else:
            cur = f"{cur}\n{line}" if cur else line
    if cur:
        chunks.append(cur)
    return chunks


def send_telegram(text):
    token, chat_id = load_telegram_creds()
    if not token or not chat_id:
        print("WARN: telegram creds missing (pendle_reporter); skipping send", file=sys.stderr)
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    ok = True
    for chunk in _chunk(text):
        body = urlencode({
            "chat_id": chat_id,
            "text": chunk,
            "parse_mode": "HTML",
            "disable_web_page_preview": "true",
        }).encode("utf-8")
        try:
            with urlopen(Request(url, data=body, method="POST"), timeout=FETCH_TIMEOUT) as resp:
                resp.read()
        except (URLError, HTTPError) as e:
            print(f"ERROR: telegram send failed: {e}", file=sys.stderr)
            ok = False
    return ok


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #

def main():
    parser = argparse.ArgumentParser(description="Pendle positions digest (by wallet)")
    parser.add_argument("--print", dest="print_only", action="store_true",
                        help="Render to stdout without sending")
    parser.add_argument("--dry-run", dest="print_only", action="store_true",
                        help="Alias for --print")
    args = parser.parse_args()

    now = datetime.now(timezone.utc)

    feed = load_json(FEED_PATH)
    if not feed or not feed.get("positions"):
        print("No Pendle holdings feed / no positions; nothing to send.", file=sys.stderr)
        return 0

    snapshot = load_json(SNAPSHOT_PATH)
    market_index = index_markets(snapshot)

    snapshot_age_h = _age_hours(snapshot.get("generated_at"), now) if snapshot else None
    feed_age_h = _age_hours(feed.get("generated_at"), now)

    msg = render_digest(feed, market_index, now, snapshot_age_h, feed_age_h)

    if args.print_only:
        print(msg)
        return 0

    return 0 if send_telegram(msg) else 1


if __name__ == "__main__":
    sys.exit(main())
