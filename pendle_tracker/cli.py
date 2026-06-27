"""
Ad-hoc Pendle queries.

  python -m pendle_tracker snapshot             # run + write DB + JSON projection
  python -m pendle_tracker list                 # latest records (from snapshot)
  python -m pendle_tracker query --market PT-srUSDat-27AUG2026
  python -m pendle_tracker query --market PT-srUSDat-27AUG2026 --field pt_implied_apy
  python -m pendle_tracker query --market PT-srUSDat-27AUG2026 --live
"""

import argparse
import json
import logging
import sys

from . import collector


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

    if args.cmd == "query":
        key = _find_key(args.market)
        out = collector.query(key=key, field=args.field, live=args.live)
        print(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    main()
