"""Explicit PT inventory export; no holdings, DB, Sheets, alerts or cron edits."""
import argparse
import json
import os
from pathlib import Path
from pendle_tracker.pt_inventory import discover,legacy_audit,feed_projection


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',required=True);p.add_argument('--legacy-index');p.add_argument('--raw-out');args=p.parse_args()
    if args.raw_out and Path(args.raw_out).resolve()==Path(args.out).resolve():p.error('--out and --raw-out must differ')
    result=discover()
    if args.legacy_index:
        legacy=json.loads(Path(args.legacy_index).read_text());result['legacy_audit']=legacy_audit(legacy)
        keys={(int(cid),address.lower()) for cid,group in legacy.get('chains',{}).items() for address in group.get('markets',{})}
        live=[r for r in result['markets'] if r['maturity_state']=='unexpired_ge_7d']
        result['legacy_audit']['summary']['new_unexpired_ge_7d_not_in_legacy_index']=sum((r['chain_id'],r['market_address']) not in keys for r in live)
        official={(r['chain_id'],r['market_address']) for r in result['markets']}
        result['legacy_audit']['summary']['legacy_unexpired_ge_7d_absent_from_official_directory']=sum(
            r['actual_days_remaining'] is not None and r['actual_days_remaining']>=7 and
            (r['chain_id'],r['market_address'].lower()) not in official for r in result['legacy_audit']['rows'])
    if args.raw_out:
        path=Path(args.raw_out);path.parent.mkdir(parents=True,exist_ok=True);tmp=path.with_name(path.name+'.tmp')
        tmp.write_text(json.dumps(result,indent=2,allow_nan=False)+'\n');os.replace(tmp,path)
    target=Path(args.out);target.parent.mkdir(parents=True,exist_ok=True);temporary=target.with_name(target.name+'.tmp')
    temporary.write_text(json.dumps(feed_projection(result),indent=2,allow_nan=False)+'\n');os.replace(temporary,target)
    print(json.dumps(result['summary'],indent=2))
    if result.get('legacy_audit'):print('Legacy index audit:',json.dumps(result['legacy_audit']['summary']))
