"""
Ad-hoc Pendle queries.

  python -m pendle_tracker snapshot             # run + write DB + JSON projection
  python -m pendle_tracker list                 # latest records (from snapshot)
  python -m pendle_tracker query --market PT-srUSDat-27AUG2026
  python -m pendle_tracker query --market PT-srUSDat-27AUG2026 --field pt_implied_apy
  python -m pendle_tracker query --market PT-srUSDat-27AUG2026 --live
  python -m pendle_tracker index
  python -m pendle_tracker top --by implied_apy --n 20
  python -m pendle_tracker top --by yt_floating_apy --n 10
"""

import argparse
import json
import logging
import sys

from . import collector
from . import index as market_index


def _find_key(partial):
    """Allow fuzzy market keys on the CLI (e.g. 'srusdat')."""
    from .watchlist import WATCHLIST
    p = partial.lower()
    exact = [e["key"] for e in WATCHLIST if e["key"].lower() == p]
    if exact:
        return exact[0]
    matches = [e["key"] for e in WATCHLIST if p in e["key"].lower()]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        print(f"ambiguous '{partial}' -> {matches}", file=sys.stderr)
    return partial


def main(argv=None):
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    p = argparse.ArgumentParser(prog="pendle_tracker")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("snapshot", help="run watchlist, write DB + JSON projection")
    sub.add_parser("list", help="print latest records from snapshot")
    sub.add_parser("index", help="sweep active ETH Pendle markets into DB + index projection")

    top = sub.add_parser("top", help="rank latest indexed markets")
    top.add_argument("--by", choices=sorted(market_index.RANK_FIELDS), required=True)
    top.add_argument("--n", type=int, default=20)

    q = sub.add_parser("query", help="look up one market")
    q.add_argument("--market", "-m", required=True)
    q.add_argument("--field", "-f", default=None)
    q.add_argument("--live", action="store_true", help="fetch live instead of snapshot")

    args = p.parse_args(argv)

    if args.cmd == "snapshot":
        snap = collector.snapshot(write=True)
        print(f"{len(snap['markets'])} markets, {len(snap['errors'])} errors")
        return

    if args.cmd == "list":
        print(json.dumps(collector.query(), indent=2, default=str))
        return

    if args.cmd == "index":
        out = market_index.sweep_index(write=True)
        print(
            f"{out['records']} indexed markets, {len(out['errors'])} errors, "
            f"{out['api_calls']} API calls"
        )
        return

    if args.cmd == "top":
        print(json.dumps(market_index.top_markets(args.by, n=args.n), indent=2, default=str))
        return

    if args.cmd == "query":
        key = _find_key(args.market)
        out = collector.query(key=key, field=args.field, live=args.live)
        print(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    main()
