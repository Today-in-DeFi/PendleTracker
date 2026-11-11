"""Read-only source-owned availability/identity refresh for eight screening leads.

No quotes, simulations, grading, holdings, DB, schedules or publication.
"""
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from pendle_tracker.route_quotes import EvidenceClient, RPC, atomic_json, contract, read_batch, read_call, expiry_utc

ROOT=Path('data/research/pt-screening-availability-2026-11-05')
DISCOVERY=Path('/home/danger/riskAnalyst/data/reviews/pt-screening-coverage-2026-11-05/availability.json')
INVENTORY=Path('data/pendle_pt_inventory_latest.json')
LEADS=[(143,'0xdc66fcf20d4e8780ea9eda19d832345a2af69c42'),
 (1,'0xeb603c5a42d49d3b2e078191c23bf3f5d25bc219'),
 (1,'0x61703e1ea2887fffd4b5f777bafd6abd7122bcf9'),
 (1,'0x384509537ce5daa5740baeb6d1ee0eb2847ea8a8'),
 (1,'0xfcf009cb3135da12a6eb1f73f3ee05392a7bc947'),
 (1,'0xac028348c46d3455899a2b9b50077c11960eaddb'),
 (143,'0xa9983573da171b910ba48dd5372a0ad60f737096'),
 (143,'0x9cbc42eff240ad2e43bbdc3c0562a9b4ce842a5a')]
FAMILIES={'earnausd','sbold','superusdc','superweth','trusd','strusd','ausd'}
CANONICAL_STR='0x683fb58ee77172626d5b49087ddac71ef7825d20'
VIRTUAL_STR='0x53176cadd446700fa6b89f840357ac586d7e33db'


def timestamp():return datetime.now(timezone.utc).isoformat()
def ref(path):return {'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}

def asset_id(value):
    chain,address=value.split('-',1)
    return {'chain_id':int(chain),'address':contract(address)}


def validate_detail(source,detail):
    cid=int(source['chainId'])
    if int(detail['chainId'])!=cid or contract(detail['address'])!=contract(source['address']):raise ValueError('Market identity mismatch')
    for field in ['pt','yt','sy','underlyingAsset','accountingAsset']:
        identity=asset_id(source[field]);live=detail[field]
        if identity!={'chain_id':int(live['chainId']),'address':contract(live['address'])}:raise ValueError(field+' directory/detail mismatch')
    if expiry_utc(source['expiry'])!=expiry_utc(detail['expiry']):raise ValueError('Expiry mismatch')


def main():
    if list((ROOT/'raw').glob('*.json')):raise ValueError('Use a new run directory; prior evidence must remain immutable')
    client=EvidenceClient(ROOT/'raw')
    discovery=json.loads(DISCOVERY.read_text());inventory=json.loads(INVENTORY.read_text())
    old={(r['chain_id'],r['market_address']):r for r in inventory['markets']}
    discovery_map={(r['chainId'],r['address']):r for r in discovery['markets']}
    result={'schema_version':1,'collection_started_at':timestamp(),'scope':'Screening availability and exact identities; no recommendation, route, simulation or score',
       'inputs':{'riskAnalyst_discovery':ref(DISCOVERY),'prior_inventory':ref(INVENTORY)},
       'policy':{'risk_grades':'RiskAnalyst owned; no parent/wrapper/chain/PT grade inheritance',
                 'operational_availability':'Directory/future expiry/listing flags do not establish enabled trading, permissions, redemption availability or executable liquidity',
                 'retired':'Expired-by-time classification only; no delisting, closure or exposure-removal inference',
                 'rates':'Not collected or used for prioritization'},
       'directory':{'source':'https://api-v2.pendle.finance/core/v2/markets/all','pages':[]},'markets':[]}
    rows=[];seen=set();skip=0;total=None
    while True:
        page,evidence=client.get('/v2/markets/all',{'skip':skip,'limit':100})
        items=page.get('results',page.get('markets'))
        if not isinstance(items,list) or not isinstance(page.get('total'),int) or isinstance(page.get('total'),bool):raise ValueError('Invalid directory envelope')
        if total is not None and total!=page['total']:raise ValueError('Directory total changed during pagination')
        if page.get('skip')!=skip or page.get('limit')!=100:raise ValueError('Pagination mismatch')
        total=page['total'];result['directory']['pages'].append(evidence)
        for source in items:
            key=(int(source['chainId']),contract(source['address']))
            if key in seen:raise ValueError('Duplicate directory market')
            seen.add(key);rows.append(source)
        skip+=len(items)
        if skip==total:break
        if skip>total or not items:raise ValueError('Truncated/mismatched directory')
    result['directory'].update(total=total,returned=len(rows),completed_at=timestamp())
    selected={(int(s['chainId']),contract(s['address'])):s for s in rows if int(s['chainId']) in [1,143] and str(s.get('name','')).lower() in FAMILIES}
    # Include exact requested leads even if a display name changes.
    index={(int(s['chainId']),contract(s['address'])):s for s in rows}
    for key in LEADS:
        if key in index:selected[key]=index[key]
    for key,source in selected.items():
        maturity=expiry_utc(source['expiry']);expired=maturity<=datetime.now(timezone.utc)
        result['markets'].append({'chain_id':key[0],'market_address':key[1],'family_label':source.get('name'),
          'is_requested_lead':key in LEADS,'pt':asset_id(source['pt']),'yt':asset_id(source['yt']),'sy':asset_id(source['sy']),
          'directory_underlying':asset_id(source['underlyingAsset']),'accounting_reference':asset_id(source['accountingAsset']),
          'maturity':maturity.isoformat(),'expiry_evaluated_at':timestamp(),'expired':expired,
          'availability':'expired_by_time_not_delisted_or_closed' if expired else 'unexpired_directory_listing_operational_status_unverified',
          'directory_flags':{k:source.get(k) for k in ['isActive','isExpired','isWhitelistedPro','isWhitelistedSimple']},
          'directory_page_evidence':result['directory']['pages'][rows.index(source)//100],
          'prior_inventory_identity':None if key not in old else {'id':old[key]['id'],'fetched_at':old[key]['fetched_at']},
          'riskAnalyst_discovery_identity_matches':None if key not in discovery_map else all(discovery_map[key].get(f)==source.get(f) for f in ['pt','sy','underlyingAsset','accountingAsset','expiry']),
          'listing_is_trading_enabled':None,'executable_capacity':None,'risk_score':None})
    mapped={(r['chain_id'],r['market_address']):r for r in result['markets']}
    result['missing_requested_leads']=[{'chain_id':cid,'market_address':address} for cid,address in LEADS if (cid,address) not in mapped]
    for key in LEADS:
        if key not in mapped:continue
        row=mapped[key];source=index[key]
        try:
            detail,evidence=client.get(f'/v1/{key[0]}/markets/{key[1]}')
            validate_detail(source,detail)
            row.update(live_detail_status='exact_identity_verified',live_detail_evidence=evidence,
                pt_metadata=detail['pt'],sy_metadata=detail['sy'],underlying_metadata=detail['underlyingAsset'],accounting_metadata=detail['accountingAsset'],
                listing_flags={k:detail.get(k) for k in ['isActive','isWhitelistedPro','isWhitelistedSimple','isWhitelistedLimitOrder']},
                source_market_data_as_of=detail.get('dataUpdatedAt'),identity_observed_at=evidence['received_at'])
        except (KeyError,ValueError,TypeError) as exc:row.update(live_detail_status='unverified',error=str(exc))
        atomic_json(ROOT/'availability.json',result)
        print(key,row['live_detail_status'],flush=True)
    for cid in [1,143]:
        group=[mapped[k] for k in LEADS if k[0]==cid and k in mapped]
        actual,chain_evidence=client.rpc(cid,'eth_chainId',[])
        if int(actual,16)!=cid:raise ValueError('RPC chain mismatch')
        block,_=client.rpc(cid,'eth_blockNumber',[])
        header,header_ref=client.rpc(cid,'eth_getBlockByNumber',[block,False])
        for row in group:
            definitions=[('market_tokens',row['market_address'],'readTokens'),('pt_expiry',row['pt']['address'],'expiry'),
                ('sy_yieldToken',row['sy']['address'],'yieldToken'),('sy_assetInfo',row['sy']['address'],'assetInfo'),
                ('sy_tokensIn',row['sy']['address'],'getTokensIn'),('sy_tokensOut',row['sy']['address'],'getTokensOut')]
            if cid==1:
                observations=read_batch(client,cid,[(address,kind,'') for _,address,kind in definitions],block)
            else:
                observations=[read_call(client,cid,address,kind,block) for _,address,kind in definitions]
            reads=dict(zip([name for name,_,_ in definitions],observations))
            verified=(reads['market_tokens'].get('value')==[row['sy']['address'],row['pt']['address'],row['yt']['address']] and reads['pt_expiry'].get('value')==str(int(expiry_utc(row['maturity']).timestamp())))
            row['onchain']={'status':'exact_pt_sy_maturity_verified' if verified else 'incomplete_or_mismatch','block':block,
                'block_hash':header['hash'],'block_timestamp':int(header['timestamp'],16),'chain_evidence':chain_evidence,'header_evidence':header_ref,'reads':reads}
            atomic_json(ROOT/'availability.json',result)
            print('onchain',cid,row['family_label'],verified,flush=True)
        if cid==143:
            discrepancy=mapped[(143,'0xa9983573da171b910ba48dd5372a0ad60f737096')]
            evidence={'scope':'Monad strUSD metadata identity only; no execution/redemption route simulation',
                      'directory_reference':VIRTUAL_STR,'canonical_documented_strUSD':CANONICAL_STR,
                      'block':block,'reads':{}}
            for address in [VIRTUAL_STR,CANONICAL_STR]:
                try:
                    payload,reference=client.request('POST',RPC[cid],body={'jsonrpc':'2.0','id':1,'method':'eth_getCode','params':[address,block]})
                    evidence['reads'][address]={'code_present':bool(payload.get('result') not in [None,'0x','0x0']),'evidence':reference,'error':payload.get('error')}
                except ValueError as exc:evidence['reads'][address]={'error':str(exc)}
            evidence['sy_yieldToken']=discrepancy['onchain']['reads']['sy_yieldToken']
            evidence['sy_tokensIn']=discrepancy['onchain']['reads']['sy_tokensIn']
            evidence['sy_tokensOut']=discrepancy['onchain']['reads']['sy_tokensOut']
            evidence['canonical_decimals']=read_call(client,cid,CANONICAL_STR,'decimals',block)
            result['monad_strusd_identity_resolution']=evidence
    # Save current official Tori registry as documentary identity evidence.
    # Registry is captured separately as text; EvidenceClient intentionally stores JSON evidence.
    result['generated_at']=timestamp()
    result['summary']={'directory_entries':total,'directory_pages':len(result['directory']['pages']),
        'related_family_markets':len(result['markets']),'requested_leads':len(LEADS),'missing_leads':len(result['missing_requested_leads']),
        'lead_live_details_verified':sum(r.get('live_detail_status')=='exact_identity_verified' for r in result['markets']),
        'lead_onchain_verified':sum(r.get('onchain',{}).get('status')=='exact_pt_sy_maturity_verified' for r in result['markets']),
        'related_expired':sum(r['expired'] for r in result['markets'])}
    atomic_json(ROOT/'availability.json',result)
    print(result['summary'])

if __name__=='__main__':main()
