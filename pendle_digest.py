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
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


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
    if a >= 1_000_000:
        return f"${v/1_000_000:.2f}M"
    if a >= 1_000:
        return f"${v/1_000:.1f}K"
    return f"${v:,.0f}"


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


def build_position(pos, market_index):
    """Merge a feed position with its snapshot record into a flat render dict."""
    cid = _chain_id(pos.get("chain"))
    pt = _norm_addr(pos.get("pt_token_address"))
    rec = market_index.get((cid, pt)) or {}

    # fixed APY: prefer snapshot (percent); fall back to feed fraction.
    fixed = rec.get("pt_implied_apy")
    if fixed is None and pos.get("pt_implied_apy") is not None:
        fixed = pos["pt_implied_apy"] * 100.0

    name = rec.get("key") or pos.get("symbol") or pos.get("position_name") or "?"
    tag = CHAIN_TAG.get(cid)

    flags = [f.get("code") for f in rec.get("flags", []) if f.get("code")]

    return {
        "name": name,
        "chain_tag": tag,
        "value_usd": pos.get("value_usd") or 0.0,
        "fixed_apy": fixed,
        "days_to_maturity": rec.get("days_to_maturity"),
        "pt_discount": rec.get("pt_discount"),
        "exit_bps": rec.get("exit_slippage_bps_at_notional"),
        "days_held": pos.get("days_held"),
        "flags": flags,
        "matched": bool(rec),
    }


def group_by_wallet(feed, market_index):
    wallets = {}
    for pos in feed.get("positions", []):
        label = pos.get("wallet_label") or pos.get("wallet") or "Unknown"
        wallets.setdefault(label, []).append(build_position(pos, market_index))
    # sort positions within each wallet by value desc
    for label in wallets:
        wallets[label].sort(key=lambda p: p["value_usd"], reverse=True)
    # order wallets by total value desc
    return sorted(
        wallets.items(),
        key=lambda kv: sum(p["value_usd"] for p in kv[1]),
        reverse=True,
    )


def wavg_fixed(positions):
    num = sum((p["fixed_apy"] or 0) * p["value_usd"] for p in positions if p["fixed_apy"] is not None)
    den = sum(p["value_usd"] for p in positions if p["fixed_apy"] is not None)
    return (num / den) if den else None


# --------------------------------------------------------------------------- #
# render
# --------------------------------------------------------------------------- #

def render_position_line(idx, p):
    name = _esc(p["name"])
    if p["chain_tag"]:
        name += f" <i>({p['chain_tag']})</i>"
    head = f"{idx}. {name}  <b>{fmt_usd(p['value_usd'])}</b>"

    detail = []
    if p["fixed_apy"] is not None:
        detail.append(f"fixed {fmt_pct(p['fixed_apy'])}")
    d = p["days_to_maturity"]
    if d is not None:
        warn = " ⚠️" if "near_maturity" in p["flags"] else ""
        detail.append(f"{d:.0f}d to mat{warn}")
    if p["pt_discount"] is not None:
        detail.append(f"disc {fmt_pct(p['pt_discount'])}")
    if p["exit_bps"] is not None:
        detail.append(f"exit ~{p['exit_bps']:.0f}bps")
    if p.get("days_held") == 0:
        detail.append("new")

    lines = [head]
    if detail:
        lines.append("   " + " · ".join(detail))

    # surface any non-maturity flags explicitly (maturity already inlined above)
    extra = [FLAG_LABEL.get(c, c) for c in p["flags"] if c != "near_maturity"]
    if extra:
        lines.append("   " + " · ".join(extra))
    if not p["matched"]:
        lines.append("   <i>(no market intel — feed only)</i>")
    return "\n".join(lines)


def render_digest(feed, market_index, now, snapshot_age_h, feed_age_h):
    wallets = group_by_wallet(feed, market_index)

    total_value = sum(p["value_usd"] for _, ps in wallets for p in ps)
    total_positions = sum(len(ps) for _, ps in wallets)
    flagged = sum(1 for _, ps in wallets for p in ps if p["flags"])

    date_str = now.strftime("%Y-%m-%d")
    lines = [f"🟣 <b>TID Pendle Digest</b> — {date_str}"]

    summary = (
        f"💰 {total_positions} position{'s' if total_positions != 1 else ''} · "
        f"{len(wallets)} wallet{'s' if len(wallets) != 1 else ''} · "
        f"{fmt_usd(total_value)}"
    )
    summary += f" · ⚠️ {flagged} flagged" if flagged else " · ✅ all clear"
    lines.append(summary)

    # freshness banners
    if snapshot_age_h is not None and snapshot_age_h > SNAPSHOT_STALE_HOURS:
        lines.append(f"⚠️ <i>market intel {snapshot_age_h:.0f}h stale</i>")
    if feed_age_h is not None and feed_age_h > FEED_STALE_HOURS:
        lines.append(f"⚠️ <i>holdings feed {feed_age_h:.0f}h stale</i>")

    for label, positions in wallets:
        subtotal = sum(p["value_usd"] for p in positions)
        avg = wavg_fixed(positions)
        header = f"\n<b>{_esc(label)}</b> — {fmt_usd(subtotal)}"
        if avg is not None:
            header += f" · avg fixed {fmt_pct(avg)}"
        lines.append(header)
        for i, p in enumerate(positions, 1):
            lines.append(render_position_line(i, p))

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
