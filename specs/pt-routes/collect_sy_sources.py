"""Optional read-only Sourcify source evidence refresh for the fixed pilot manifest.

Run from repository root; does not contact Pendle, holdings or the live DB.
Use a new output directory to preserve older source observations.
"""
import json,time,requests,hashlib
from pathlib import Path
from datetime import datetime,timezone
import argparse
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--manifest',default='specs/pt-routes/candidates-2026-11-04.json')
parser.add_argument('--out-dir',required=True)
args=parser.parse_args()
manifest=json.load(open(args.manifest))
root=Path(args.out_dir) / 'sources'
if root.exists() and any(root.iterdir()):raise SystemExit('Use a new output directory to preserve evidence')
root.mkdir(parents=True,exist_ok=True)
rows=[]
for candidate in manifest['candidates']:
 cid=candidate['chain_id'];address=candidate['sy'];row={'chain_id':cid,'sy':address,'source_basis':'Sourcify verification and proxy resolution at HTTP retrieval; not pinned to quote block','observed_at':datetime.now(timezone.utc).isoformat(),'contracts':[]}
 addresses=[address]
 for index,address in enumerate(addresses):
  if index>=2:break
  url=f'https://sourcify.dev/server/v2/contract/{cid}/{address}?fields=compilation,sources,proxyResolution,abi'
  try:
   r=requests.get(url,timeout=30);r.raise_for_status();d=r.json()
   path=root/f'{cid}-{address.lower()}.json';path.write_text(json.dumps(d,indent=2)+'\n')
   contract={'address':address,'url':url,'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'match':d.get('match'),'runtime_match':d.get('runtimeMatch'),'compilation':d.get('compilation'),'proxy_resolution':d.get('proxyResolution')}
   row['contracts'].append(contract)
   for item in (d.get('proxyResolution') or {}).get('implementations',[]):
    if item['address'].lower() not in [a.lower() for a in addresses]:addresses.append(item['address'])
  except (requests.RequestException,ValueError,KeyError) as exc:row['contracts'].append({'address':address,'url':url,'status':'unavailable','error_type':type(exc).__name__})
  time.sleep(1)
 rows.append(row)
 print(cid,candidate['name'],[(x.get('compilation') or {}).get('name',x.get('status')) for x in row['contracts']],flush=True)
 (Path(args.out_dir) / 'sy_sources.json').write_text(json.dumps(rows,indent=2)+'\n')
