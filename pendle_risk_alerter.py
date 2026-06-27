#!/usr/bin/env python3
"""
Pendle PT Risk Alerter

Reads data/pendle_markets.json (written hourly by `python3 -m pendle_tracker`)
and routes per-market state transitions to Telegram —
single fire on trip, single fire on recovery. Watches three signals per market:

1. NEAR MATURITY (roll-decision countdown)
   days_to_maturity <= NEAR_MATURITY_TRIP_DAYS. A dated PT must be rolled or
   exited before maturity; this is the reminder to act. Because the countdown
   only decreases for a given market, "recovery" happens when the position rolls
   (the watchlist key changes → old key disappears, handled as a clear) — so a
   STILL-ACTIVE reminder re-fires every NEAR_MATURITY_REMINDER_DAYS while tripped.
   An expired market escalates to EXPIRED once.

2. EXIT-SLIPPAGE STRESS (can-we-get-out, at our size)
   exit_slippage_bps_at_notional (SDK swap sim of selling our notional — or the
   $100k ladder rung for collateral PTs with no notional). Trips when slippage to
   exit blows out past EXIT_SLIPPAGE_TRIP_BPS.

3. LIQUIDITY DROP (pool draining, leading indicator)
   liquidity_usd falling >= LIQ_DROP_TRIP_FRAC below a rolling baseline (median of
   recent history). Catches a draining pool even when our position is small enough
   that exit slippage hasn't moved yet. Needs history; inert until enough points.

Direction: downside only for all three. A near-maturity countdown, worse exit
slippage, and a falling pool are the only risk directions.

State-transition logic (data/pendle_alert_state.json) prevents re-firing on
unchanged data. Stdlib only.

Usage:
    python3 pendle_risk_alerter.py            # normal cron run
    python3 pendle_risk_alerter.py --verbose  # print decision trace
    python3 pendle_risk_alerter.py --dry-run  # print message without sending
"""

import argparse
import html
import json
import os
import statistics
import sys
from datetime import datetime, timezone, timedelta
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
from urllib.parse import urlencode

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(PROJECT_DIR, "data")
STATE_PATH = os.path.join(DATA_DIR, "pendle_alert_state.json")
TELEGRAM_CONFIG = os.path.join(PROJECT_DIR, "telegram_config.json")
SNAPSHOT_PATH = os.path.join(DATA_DIR, "pendle_markets.json")

FETCH_TIMEOUT = 15
SNAPSHOT_MAX_AGE_HOURS = 6   # don't fire on a stale snapshot

# --- near-maturity ---
NEAR_MATURITY_TRIP_DAYS = 14.0
NEAR_MATURITY_RECOVER_DAYS = 21.0   # only reachable if a key rolls to a longer tenor
NEAR_MATURITY_REMINDER_DAYS = 7.0   # STILL-ACTIVE re-fire cadence while tripped

# --- exit slippage ---
EXIT_SLIPPAGE_TRIP_BPS = 50.0
EXIT_SLIPPAGE_RECOVER_BPS = 30.0

# --- liquidity drop vs baseline ---
LIQ_DROP_TRIP_FRAC = 0.40       # >=40% below baseline trips
LIQ_DROP_RECOVER_FRAC = 0.20    # back within 20% of baseline recovers
LIQ_BASELINE_MIN_POINTS = 4
LIQ_BASELINE_LOOKBACK_DAYS = 7
LIQ_BASELINE_EXCLUDE_HOURS = 6  # exclude the freshest points so a drop isn't its own baseline


def load_state():
    try:
        with open(STATE_PATH) as f:
            state = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        state = {}
    state.setdefault("markets", {})
    return state


def save_state(state):
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    state["last_run_at"] = datetime.now(timezone.utc).isoformat()
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f, indent=2)
    os.replace(tmp, STATE_PATH)


def load_telegram_creds():
    with open(TELEGRAM_CONFIG) as f:
        cfg = json.load(f)
    tg = cfg.get("usd_reporter", {}).get("telegram", {})
    return tg.get("bot_token"), tg.get("chat_id")


def send_telegram(text):
    token, chat_id = load_telegram_creds()
    if not token or not chat_id:
        print("WARN: telegram creds missing; skipping send", file=sys.stderr)
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    body = urlencode({
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": "true",
    }).encode("utf-8")
    try:
        with urlopen(Request(url, data=body, method="POST"), timeout=FETCH_TIMEOUT) as resp:
            resp.read()
        return True
    except (URLError, HTTPError) as e:
        print(f"ERROR: telegram send failed: {e}", file=sys.stderr)
        return False


def _parse_ts(ts):
    if not ts:
        return None
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def read_snapshot():
    try:
        with open(SNAPSHOT_PATH) as f:
            snap = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"WARN: could not read {SNAPSHOT_PATH}: {e}", file=sys.stderr)
        return None
    return snap


def read_history():
    snap = read_snapshot()
    if not snap:
        return {"markets": {}}
    try:
        from pendle_tracker import history as db_history
    except ImportError as exc:
        print(f"WARN: could not import Pendle DB history API: {exc}", file=sys.stderr)
        return {"markets": {}}

    markets = {}
    for market in snap.get("markets", []):
        key = market.get("key")
        if not key:
            continue
        entries = []
        for row in db_history(key, days=LIQ_BASELINE_LOOKBACK_DAYS + 1):
            item = dict(row)
            item.setdefault("timestamp", item.get("ts"))
            entries.append(item)
        markets[key] = {"entries": entries}
    return {"markets": markets}


def liquidity_baseline(history, key, now):
    """Median liquidity_usd over the lookback window, excluding the freshest points.
    Returns None if insufficient history."""
    entries = history.get("markets", {}).get(key, {}).get("entries", [])
    lookback_start = now - timedelta(days=LIQ_BASELINE_LOOKBACK_DAYS)
    exclude_after = now - timedelta(hours=LIQ_BASELINE_EXCLUDE_HOURS)
    vals = []
    for e in entries:
        liq = e.get("liquidity_usd")
        when = _parse_ts(e.get("timestamp"))
        if liq is None or when is None:
            continue
        if lookback_start <= when <= exclude_after:
            vals.append(liq)
    if len(vals) < LIQ_BASELINE_MIN_POINTS:
        return None
    return statistics.median(vals)


# --- decision functions (downside-only hysteresis) ---

def decide_near_maturity(prev_status, days, expired):
    if days is None:
        return None, None
    if expired or days <= 0:
        return ("EXPIRED", "expired") if prev_status != "EXPIRED" else ("EXPIRED", None)
    if prev_status in ("TRIPPED", "EXPIRED"):
        if days > NEAR_MATURITY_RECOVER_DAYS:
            return "OK", "recovered"
        return "TRIPPED", None
    if days <= NEAR_MATURITY_TRIP_DAYS:
        return "TRIPPED", "tripped"
    return "OK", None


def decide_exit_slippage(prev_status, slippage_bps):
    if slippage_bps is None:
        return None, None
    if prev_status == "TRIPPED":
        if slippage_bps <= EXIT_SLIPPAGE_RECOVER_BPS:
            return "OK", "recovered"
        return "TRIPPED", None
    if slippage_bps >= EXIT_SLIPPAGE_TRIP_BPS:
        return "TRIPPED", "tripped"
    return "OK", None


def decide_liquidity_drop(prev_status, liquidity_usd, baseline):
    if liquidity_usd is None or baseline is None or baseline <= 0:
        return None, None
    drop = 1.0 - (liquidity_usd / baseline)   # positive = below baseline
    if prev_status == "TRIPPED":
        if drop <= LIQ_DROP_RECOVER_FRAC:
            return "OK", "recovered"
        return "TRIPPED", None
    if drop >= LIQ_DROP_TRIP_FRAC:
        return "TRIPPED", "tripped"
    return "OK", None


def _esc(s):
    return html.escape(str(s), quote=False) if s is not None else ""


def format_message(transitions):
    if not transitions:
        return None
    lines = ["<b>🚨 Pendle PT risk-flag CHANGE</b>"]
    # group by market for readability
    by_market = {}
    for t in transitions:
        by_market.setdefault(t["market"], []).append(t)

    for market, ts in by_market.items():
        exp = ts[0].get("exposure")
        tag = f" ({exp})" if exp else ""
        lines.append(f"\n<b>{_esc(market)}</b>{tag}")
        for t in ts:
            sig, kind = t["signal"], t["kind"]
            if sig == "near_maturity":
                if kind == "expired":
                    lines.append(f"🚨 <b>EXPIRED</b> — PT redeemable 1:1; roll the watchlist entry")
                elif kind == "tripped":
                    lines.append(f"⏳ <b>NEAR MATURITY</b> — {t['days']:.1f}d left "
                                 f"(≤ {NEAR_MATURITY_TRIP_DAYS:.0f}d) — roll/exit decision")
                elif kind == "reminder":
                    lines.append(f"⏳ <b>STILL NEAR MATURITY</b> — {t['days']:.1f}d left")
                else:
                    d = t.get("days")
                    if d is None or d != d:  # None or NaN → key left the watchlist
                        lines.append("✅ <b>ALERTS CLEARED</b> — position rolled or closed")
                    else:
                        lines.append(f"✅ <b>MATURITY CLEARED</b> — {d:.1f}d left (rolled)")
            elif sig == "exit_slippage":
                slip = t["slippage_bps"]
                notion = t.get("notional_usd")
                size = f"${notion/1000:.0f}k" if notion else "$100k"
                if kind == "tripped":
                    lines.append(f"🚨 <b>EXIT-LIQUIDITY STRESS</b> — exit {size} ≈ {slip:.0f}bps "
                                 f"(trip ≥ {EXIT_SLIPPAGE_TRIP_BPS:.0f}bps)")
                else:
                    lines.append(f"✅ <b>EXIT LIQUIDITY OK</b> — exit {size} ≈ {slip:.0f}bps "
                                 f"(≤ {EXIT_SLIPPAGE_RECOVER_BPS:.0f}bps)")
            elif sig == "liquidity_drop":
                liq, base = t["liquidity_usd"], t["baseline"]
                drop_pct = (1.0 - liq / base) * 100 if base else 0
                if kind == "tripped":
                    lines.append(f"🚨 <b>LIQUIDITY DRAIN</b> — ${liq:,.0f} pool, "
                                 f"{drop_pct:.0f}% below ${base:,.0f} baseline "
                                 f"(trip ≥ {LIQ_DROP_TRIP_FRAC*100:.0f}%)")
                else:
                    lines.append(f"✅ <b>LIQUIDITY RESTORED</b> — ${liq:,.0f} pool, "
                                 f"{drop_pct:.0f}% vs baseline")

    lines.append(f"\nsource: pendle_markets.json  ·  state: {_esc(os.path.basename(STATE_PATH))}")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Pendle PT risk alerter (maturity + liquidity)")
    parser.add_argument("--verbose", action="store_true", help="Print decision trace")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print the Telegram message that would be sent without firing it")
    args = parser.parse_args()

    now = datetime.now(timezone.utc)
    state = load_state()
    snap = read_snapshot()
    if not snap:
        return 0

    gen = _parse_ts(snap.get("generated_at"))
    if gen is not None:
        age_h = (now - gen).total_seconds() / 3600
        if age_h > SNAPSHOT_MAX_AGE_HOURS:
            print(f"WARN: snapshot stale ({age_h:.1f}h > {SNAPSHOT_MAX_AGE_HOURS}h); not alerting",
                  file=sys.stderr)
            return 0

    history = read_history()
    markets = {m["key"]: m for m in snap.get("markets", [])}
    transitions = []

    for key, m in markets.items():
        ms = state["markets"].setdefault(key, {})
        exposure = m.get("exposure")
        days = m.get("days_to_maturity")
        expired = bool(m.get("expired"))
        slip = m.get("exit_slippage_bps_at_notional")
        notional = m.get("our_notional_usd")
        liq = m.get("liquidity_usd")
        baseline = liquidity_baseline(history, key, now)

        # 1. near maturity
        prev = ms.get("near_maturity_status", "OK")
        new, kind = decide_near_maturity(prev, days, expired)
        if new is not None:
            ms["near_maturity_status"] = new
            if kind:
                ms["near_maturity_last_alert_at"] = now.isoformat()
                transitions.append({"market": key, "exposure": exposure,
                                    "signal": "near_maturity", "kind": kind, "days": days})
            elif new in ("TRIPPED", "EXPIRED"):
                # STILL-ACTIVE reminder while unresolved
                last = _parse_ts(ms.get("near_maturity_last_alert_at"))
                if last is None or (now - last) >= timedelta(days=NEAR_MATURITY_REMINDER_DAYS):
                    ms["near_maturity_last_alert_at"] = now.isoformat()
                    transitions.append({"market": key, "exposure": exposure,
                                        "signal": "near_maturity", "kind": "reminder", "days": days})

        # 2. exit slippage
        prev = ms.get("exit_slippage_status", "OK")
        new, kind = decide_exit_slippage(prev, slip)
        if new is not None:
            ms["exit_slippage_status"] = new
            if kind:
                transitions.append({"market": key, "exposure": exposure,
                                    "signal": "exit_slippage", "kind": kind,
                                    "slippage_bps": slip, "notional_usd": notional})

        # 3. liquidity drop
        prev = ms.get("liquidity_status", "OK")
        new, kind = decide_liquidity_drop(prev, liq, baseline)
        if new is not None:
            ms["liquidity_status"] = new
            if kind:
                transitions.append({"market": key, "exposure": exposure,
                                    "signal": "liquidity_drop", "kind": kind,
                                    "liquidity_usd": liq, "baseline": baseline})

        if args.verbose:
            print(f"  {key}: days={days} slip={slip} liq={liq} baseline={baseline} "
                  f"states={{m:{ms.get('near_maturity_status')},s:{ms.get('exit_slippage_status')},"
                  f"l:{ms.get('liquidity_status')}}}")

    # Clear keys that left the watchlist (rolled / closed): emit one resolution if
    # any signal was active, then drop from state.
    for key in [k for k in state["markets"] if k not in markets]:
        ms = state["markets"][key]
        was_active = any(ms.get(s) in ("TRIPPED", "EXPIRED")
                         for s in ("near_maturity_status", "exit_slippage_status", "liquidity_status"))
        if was_active:
            transitions.append({"market": key, "exposure": None,
                                "signal": "near_maturity", "kind": "recovered", "days": float("nan")})
        del state["markets"][key]

    msg = format_message(transitions)

    if args.dry_run:
        print(msg if msg else "(no transitions; nothing would be sent)")
        return 0

    save_state(state)

    if msg is None:
        if args.verbose:
            print("No transitions; no alert sent.")
        return 0

    return 0 if send_telegram(msg) else 1


if __name__ == "__main__":
    sys.exit(main())
