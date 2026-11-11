"""Read token decimals and extra deposit previews at saved SY observation blocks."""
import argparse
import fcntl
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from pendle_tracker.route_quotes import EvidenceClient, read_batch, atomic_json, contract

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--resume');p.add_argument('--quotes',action='append',required=True);p.add_argument('--raw-dir',required=True);p.add_argument('--out',required=True)
a=p.parse_args()
if list(Path(a.raw_dir).glob('*.json')):raise ValueError('Use empty evidence directory')
rows={}
for source in a.quotes:
 for row in json.loads(Path(source).read_text())['markets']:
  if row['status']=='collected':rows[(row['identity']['chain_id'],row['identity']['market_address'])]=row
result=json.loads(Path(a.resume).read_text()) if a.resume else []
completed={(r["chain_id"],r["market_address"]) for r in result}
with open('/tmp/pendle_route_quotes.lock','w') as lock:
 fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 client=EvidenceClient(a.raw_dir)
 for identity,row in rows.items():
  if identity in completed:continue
  cid=identity[0];sy=row['identity']['sy'];block=hex(row['onchain_sy']['block_number'])
  tokens=row['sy_tokens'];addresses=sorted({contract(t) for t in tokens['tokensMintSy']+tokens['tokensRedeemSy']+[row['identity']['pt']]})
  reads=read_batch(client,cid,[(t,'decimals','') for t in addresses],block)
  metadata=dict(zip(addresses,reads));calls=[];names=[]
  for token in tokens['tokensMintSy']:
   token=contract(token);obs=metadata[token]
   if obs['status']=='read' and 0<=int(obs['value'])<=36:
    argument=token[2:].zfill(64)+hex(10**int(obs['value']))[2:].zfill(64)
    calls.append((sy,'previewDeposit',argument));names.append(token)
  previews=read_batch(client,cid,calls,block)
  pt_decimals = None
  for quote in row['quotes']:
   for route in quote.get('routes', []):
    for side in ['input','output']:
     if route[side]['address']==contract(row['identity']['pt']):pt_decimals=route[side]['decimals']
  if metadata[contract(row['identity']['pt'])].get('value')!=str(pt_decimals):
   raise ValueError('PT decimals mismatch against quote')
  result.append({'chain_id':cid,'market_address':identity[1],'block':block,'token_metadata':metadata,'preview_deposit_one_token':dict(zip(names,previews))})
  atomic_json(a.out,result)
  print(cid,row['identity']['name'],'units verified',flush=True)
