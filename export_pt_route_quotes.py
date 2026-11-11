"""Explicit, bounded PT route quote research export; never scheduled."""
import argparse
from pendle_tracker.route_quotes import export

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inventory', default='data/pendle_pt_inventory_latest.json')
    parser.add_argument('--candidates', default='specs/pt-routes/candidates-2026-11-04.json')
    parser.add_argument('--out', required=True)
    parser.add_argument('--raw-dir', required=True)
    parser.add_argument('--max-markets', type=int, default=11)
    parser.add_argument('--market', action='append', help='Exact chain:market from manifest; repeat to select a subset')
    args = parser.parse_args()
    print(export(args.inventory, args.candidates, args.out, args.raw_dir, args.max_markets, args.market)['summary'])
