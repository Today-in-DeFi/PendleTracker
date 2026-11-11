"""Targeted follow-up for V2 allocation adapters and Monad single-call reads."""
import json
import sys
from datetime import datetime,timezone
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from pendle_tracker.route_quotes import EvidenceClient, RPC, read_call, contract, expiry_utc, atomic_json
ROOT=Path('data/research/pt-collateral-identity-2026-11-05')
p=json.loads((ROOT/'identities.json').read_text())
client=EvidenceClient(ROOT/'followup-raw')
if list((ROOT/'followup-raw').glob('*.json')):raise ValueError('Preserve existing followup evidence')
# Keep errors from the original batch; use single allowlisted reads as a bounded fallback.
rows=[r for r in p['markets'] if r['chain_id']==143 and r['onchain_identity']['status']=='unavailable']
if rows:
 cid=143
 chain,chain_ref=client.rpc(cid,'eth_chainId',[])
 if int(chain,16)!=cid:raise ValueError('RPC chain mismatch')
 block,_=client.rpc(cid,'eth_blockNumber',[])
 header,hr=client.rpc(cid,'eth_getBlockByNumber',[block,False])
 for row in rows:
  reads={}
  for name,address,kind in [('market_readTokens',row['pendle_market_address'],'readTokens'),('pt_expiry',row['pt_address'],'expiry'),('sy_yieldToken',row['sy_address'],'yieldToken'),('sy_assetInfo',row['sy_address'],'assetInfo')]:
   reads[name]=read_call(client,cid,address,kind,block)
  verified=(reads['market_readTokens'].get('value')==[row['sy_address'],row['pt_address'],row['yt_address']] and reads['pt_expiry'].get('value')==str(int(expiry_utc(row['maturity']).timestamp())))
  row['onchain_identity']={'previous_attempt':row['onchain_identity'],'status':'verified' if verified else 'incomplete_or_mismatch',
     'rpc':RPC[cid],'chain_evidence':chain_ref,'header_before':header,'header_before_evidence':hr,'block_binding':'explicit block number','reads':reads}
  if verified:row['status']='api_and_onchain_identity_verified'
  print(row['queue_symbol'],'single-call onchain',verified,flush=True)
 atomic_json(ROOT/'identities.json',p)
market_fields='marketId chain{id} collateralAsset{address symbol} loanAsset{address symbol}'
query='''query($a:String!,$c:Int!){vaultV2ByAddress(address:$a,chainId:$c){adapters(first:20){pageInfo{countTotal} items{address type assetsUsd
... on MorphoMarketV1Adapter{positions(first:50){pageInfo{countTotal} items{state{supplyAssetsUsd} market{'''+market_fields+'''}}}}
... on MetaMorphoAdapter{metaMorpho{address state{allocation{supplyAssetsUsd withdrawQueueIndex market{'''+market_fields+'''}}}}}
}}}}'''
for index,previous in enumerate(p['live_expired_allocation_checks']):
 if previous['status']=='queried':continue
 cid=previous['chain_id'];address=previous['vault_address']
 check={'chain_id':cid,'vault_address':address,'vault_name':previous['vault_name'],'status':'unavailable','allocations':[],'previous_attempt':previous}
 try:
  data,ref=client.request('POST','https://api.morpho.org/graphql',body={'query':query,'variables':{'a':address,'c':cid}})
  if data.get('errors'):raise ValueError(str(data['errors']))
  adapters=data['data']['vaultV2ByAddress']['adapters']
  if len(adapters['items'])!=adapters['pageInfo']['countTotal']:raise ValueError('Truncated adapter list')
  targets={r['pt_address'] for r in p['markets'] if r['chain_id']==cid and r['expired_now']}
  for ai,adapter in enumerate(adapters['items']):
   positions=adapter.get('positions')
   candidates=[]
   if positions is not None:
    if len(positions['items'])!=positions['pageInfo']['countTotal']:raise ValueError('Truncated adapter positions')
    candidates += [(item['market'],(item.get('state') or {}).get('supplyAssetsUsd'),f'/data/vaultV2ByAddress/adapters/items/{ai}/positions/items/{pi}') for pi,item in enumerate(positions['items'])]
   meta=adapter.get('metaMorpho')
   if meta:
    # These are the nested vault's lender positions; do not imply parent-vault proportional exposure.
    candidates += [(item['market'],item['supplyAssetsUsd'],f'/data/vaultV2ByAddress/adapters/items/{ai}/metaMorpho/state/allocation/{pi}') for pi,item in enumerate((meta.get('state') or {}).get('allocation') or [])]
   for market,value,pointer in candidates:
    token=market.get('collateralAsset')
    if token and int(market['chain']['id'])==cid and contract(token['address']) in targets:
     check['allocations'].append({'pt_address':contract(token['address']),'morpho_market_id':market['marketId'],
         'vault_supply_position_usd':value,'loan_asset':market['loanAsset'],'source_json_pointer':pointer,
         'adapter_address':adapter['address'],'adapter_type':adapter['type'],
         'position_scope':'nested MetaMorpho lender position; parent allocation not inferred' if '/metaMorpho/' in pointer else 'direct V2 market-adapter lender position'})
  check.update(status='queried',evidence=ref,observed_at=ref['received_at'])
 except (ValueError,KeyError,TypeError) as exc:check['failure_reason']=str(exc)
 p['live_expired_allocation_checks'][index]=check
 atomic_json(ROOT/'identities.json',p)
 print(previous['vault_name'],'V2 check',check['status'],len(check['allocations']),flush=True)
p['generated_at']=datetime.now(timezone.utc).isoformat()
p['summary'].update(api_and_onchain_verified=sum(r['status']=='api_and_onchain_identity_verified' for r in p['markets']),
  positive_expired_allocation_rows=sum(float(a['vault_supply_position_usd'] or 0)>0 for c in p['live_expired_allocation_checks'] for a in c['allocations']))
atomic_json(ROOT/'identities.json',p)
