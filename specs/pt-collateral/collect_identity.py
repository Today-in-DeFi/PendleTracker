"""Exact PT collateral linkage research; no routes, grades, holdings or writes to producers."""
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from pendle_tracker.route_quotes import EvidenceClient, RPC, atomic_json, contract, read_batch, expiry_utc

ROOT = Path('data/research/pt-collateral-identity-2026-11-05')
QUEUE = Path('/home/danger/farmAnalyst/artifacts/lending_coverage_2026-11-05/prioritized-review-queue.json')
DISCOVERY = QUEUE.with_name('discovery.json')
INVENTORY = Path('data/pendle_pt_inventory_latest.json')
ROUTES = Path('data/pendle_pt_route_quotes_latest.json')
MORPHO = 'https://api.morpho.org/graphql'
RPC[999] = 'https://rpc.hyperliquid.xyz/evm'
PRIORITY = [(1,'pt-reusd'),(1,'pt-usd3'),(1,'pt-usdat'),(143,'pt-reusd'),(143,'pt-usdat')]


def file_ref(path):
    return {'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}


def select_exact(rows, chain, pt):
    found=[r for r in rows if r['chain_id']==chain and contract((r.get('tokens',{}).get('pt') or {}).get('address'))==contract(pt)]
    if len(found)!=1:raise ValueError('Exact chain/PT mapping absent or ambiguous')
    return found[0]


def verify_api(row, detail):
    cid=row['chain_id'];market=contract(row['market_address'])
    if int(detail['chainId'])!=cid or contract(detail['address'])!=market:raise ValueError('Live market mismatch')
    for role, field in [('pt','pt'),('sy','sy'),('underlying','underlyingAsset'),('yt','yt')]:
        info=detail[field]
        if int(info['chainId'])!=cid or contract(info['address'])!=contract(row['tokens'][role]['address']):
            raise ValueError(role+' identity changed or mismatched')
    if expiry_utc(detail['expiry'])!=expiry_utc(row['maturity']):raise ValueError('Maturity mismatch')


def main():
    if list((ROOT/'raw').glob('*.json')):raise ValueError('Evidence exists; preserve this run and use a new run directory')
    queue=json.loads(QUEUE.read_text());discovery=json.loads(DISCOVERY.read_text())
    inventory=json.loads(INVENTORY.read_text());routes=json.loads(ROUTES.read_text())
    queue_pts=[r for r in queue['assets'] if r['asset']['symbol'].startswith('PT-')]
    def priority(item):
        return next((i for i,(cid,prefix) in enumerate(PRIORITY) if item['chain_id']==cid and item['asset']['symbol'].lower().startswith(prefix+'-')),len(PRIORITY))
    queue_pts.sort(key=priority)
    client=EvidenceClient(ROOT/'raw')
    result={'schema_version':1,'collection_started_at':datetime.now(timezone.utc).isoformat(),
        'scope':'Exact Morpho PT collateral deployment identities only; no route/score gate added',
        'policy':{'risk_grades':'RiskAnalyst only; no scores copied or assigned and no cross-chain/wrapper inheritance',
                  'expiry':'Expired identities and reported allocations retained. Maturity alone does not establish bad debt or closure.',
                  'allocation_units':'Vault lender supply in USD in a collateral-labelled Morpho market, not borrower collateral quantity or bad debt.',
                  'source_scope':'13 PT entries from fixed queue; targeted live rechecks of previously reported expired-PT vaults, not all-market completeness'},
        'input_evidence':{'queue':file_ref(QUEUE),'discovery':file_ref(DISCOVERY),'inventory':file_ref(INVENTORY),'prior_routes':file_ref(ROUTES)},
        'queue_as_of':queue['as_of'],'allocation_snapshot_as_of':discovery['retrieved_at'],
        'inventory_generated_at':inventory['generated_at'],'prior_routes_generated_at':routes['generated_at'],
        'markets':[],'live_expired_allocation_checks':[]}
    for queued in queue_pts:
        cid=queued['chain_id'];pt=contract(queued['asset']['address'])
        row=select_exact(inventory['markets'],cid,pt)
        record={'chain_id':cid,'pt_address':pt,'queue_symbol':queued['asset']['symbol'],
                'pendle_market_address':row['market_address'],'sy_address':row['tokens']['sy']['address'],
                'yt_address':row['tokens']['yt']['address'],'underlying':row['tokens']['underlying'],
                'accounting_reference':row['tokens']['accounting'],'maturity':row['maturity'],
                'maturity_evaluated_at':datetime.now(timezone.utc).isoformat(),
                'expired_now':expiry_utc(row['maturity'])<=datetime.now(timezone.utc),
                'inventory_fetched_at':row['fetched_at'],'inventory_source_data_as_of':row.get('source_data_as_of'),
                'queue_affected_above_hurdle_vaults':queued.get('promising_vault_ids',[]),
                'queue_vault_ids':queued['vault_ids'],'morpho_snapshot_allocations':[],
                'status':'inventory_linked','risk_assessment_status':'not_assigned; RiskAnalyst scope decision required'}
        for vi,vault in enumerate(discovery['vaults']):
            for ei,exposure in enumerate(vault.get('allocation_analysis',{}).get('exposures',[])):
                if exposure.get('chain_id')==cid and exposure.get('collateral_asset') and contract(exposure['collateral_asset']['address'])==pt:
                    record['morpho_snapshot_allocations'].append({'vault_id':vault['id'],'vault_name':vault['name'],
                        'vault_address':vault['address'],'vault_version':vault['version'],
                        'vault_supply_position_usd':exposure.get('position_usd'),'morpho_market_id':exposure['market_id'],
                        'loan_asset':exposure['loan_asset'],'lltv':exposure.get('lltv'),'oracle_address':exposure.get('oracle_address'),
                        'source_json_pointer':f'/vaults/{vi}/allocation_analysis/exposures/{ei}'})
        prior=[r for r in routes['markets'] if r['identity']['chain_id']==cid and contract(r['identity']['pt'])==pt]
        record['reused_route_linkage']=None if not prior else {'identity':prior[0]['identity'],'identity_evidence':prior[0].get('identity_evidence'),
                    'onchain_identity_read':prior[0].get('onchain_sy',{}).get('market_tokens'),
                    'usage':'Identity evidence reused only; quote results not rerun or used as an assessment gate'}
        try:
            detail,ref=client.get(f'/v1/{cid}/markets/{row["market_address"]}')
            verify_api(row,detail)
            record.update(status='official_api_identity_verified',official_api_evidence=ref,
                          official_api_url=f'https://api-v2.pendle.finance/core/v1/{cid}/markets/{row["market_address"]}',
                          live_detail_source_data_as_of=detail.get('dataUpdatedAt'),
                          live_api_accounting_reference=detail.get('accountingAsset'),
                          identity_observed_at=ref['received_at'])
        except (ValueError,KeyError,TypeError) as exc:record['live_api_error']=str(exc)
        result['markets'].append(record)
        atomic_json(ROOT/'identities.json',result)
        print(cid,record['queue_symbol'],record['status'],'expired',record['expired_now'],flush=True)
    # Onchain reads only; fixed blocks on ETH/Monad. HyperEVM supports latest state
    # only on its default endpoint, so preserve surrounding headers without calling it pinned.
    for cid in sorted({r['chain_id'] for r in result['markets']}):
        rows=[r for r in result['markets'] if r['chain_id']==cid]
        try:
            chain,chain_ref=client.rpc(cid,'eth_chainId',[])
            if int(chain,16)!=cid:raise ValueError('RPC chain mismatch')
            block,_=client.rpc(cid,'eth_blockNumber',[])
            header,header_ref=client.rpc(cid,'eth_getBlockByNumber',[block,False])
            tag='latest' if cid==999 else block
            for start in range(0,len(rows),4):
                subset=rows[start:start+4];calls=[]
                for row in subset:
                    calls += [(row['pendle_market_address'],'readTokens',''),(row['pt_address'],'expiry',''),
                              (row['sy_address'],'yieldToken',''),(row['sy_address'],'assetInfo','')]
                observations=read_batch(client,cid,calls,tag)
                for i,row in enumerate(subset):
                    reads=dict(zip(['market_readTokens','pt_expiry','sy_yieldToken','sy_assetInfo'],observations[i*4:i*4+4]))
                    expected=[row['sy_address'],row['pt_address'],row['yt_address']]
                    verified=(reads['market_readTokens'].get('value')==expected and
                              reads['pt_expiry'].get('value')==str(int(expiry_utc(row['maturity']).timestamp())))
                    row['onchain_identity']={'status':'verified' if verified else 'incomplete_or_mismatch',
                        'rpc':RPC[cid],'chain_evidence':chain_ref,'header_before':header,'header_before_evidence':header_ref,
                        'block_binding':'latest calls; surrounding headers only, not block-pinned' if cid==999 else 'explicit block number',
                        'reads':reads}
                    if verified:row['status']='api_and_onchain_identity_verified' if row['status']=='official_api_identity_verified' else 'onchain_identity_verified'
            if cid==999:
                after,_=client.rpc(cid,'eth_blockNumber',[])
                h,hr=client.rpc(cid,'eth_getBlockByNumber',[after,False])
                for row in rows:row['onchain_identity'].update(header_after=h,header_after_evidence=hr)
        except (ValueError,KeyError,TypeError) as exc:
            for row in rows:row.setdefault('onchain_identity',{'status':'unavailable','reason':str(exc)})
        atomic_json(ROOT/'identities.json',result)
        print('chain',cid,'onchain checks complete',flush=True)
    # Preserve all historic rows and refresh only the expired collateral vaults.
    jobs={}
    for row in result['markets']:
        if row['expired_now']:
            for allocation in row['morpho_snapshot_allocations']:
                jobs[(row['chain_id'],allocation['vault_address'])]=allocation
    query='query($a:String!,$c:Int!){vaultByAddress(address:$a,chainId:$c){state{allocation{supplyAssetsUsd withdrawQueueIndex market{marketId chain{id} collateralAsset{address symbol} loanAsset{address symbol}}}}}}'
    for (cid,address),allocation in jobs.items():
        check={'chain_id':cid,'vault_address':address,'vault_name':allocation['vault_name'],'status':'unavailable','allocations':[]}
        try:
            if allocation['vault_version']!=1:raise ValueError('V2 adapter exposure not covered by V1 query')
            data,ref=client.request('POST',MORPHO,body={'query':query,'variables':{'a':address,'c':cid}})
            if data.get('errors'):raise ValueError(str(data['errors']))
            current=data['data']['vaultByAddress']['state']['allocation']
            if not isinstance(current,list):raise ValueError('Allocation missing')
            targets={r['pt_address'] for r in result['markets'] if r['chain_id']==cid and r['expired_now']}
            check.update(status='queried',evidence=ref,observed_at=ref['received_at'])
            for index,entry in enumerate(current):
                market=entry['market'];token=market.get('collateralAsset')
                if token and int(market['chain']['id'])==cid and contract(token['address']) in targets:
                    check['allocations'].append({'pt_address':contract(token['address']),'morpho_market_id':market['marketId'],
                        'vault_supply_position_usd':entry['supplyAssetsUsd'],'loan_asset':market['loanAsset'],
                        'withdraw_queue_index':entry.get('withdrawQueueIndex'),'source_json_pointer':f'/data/vaultByAddress/state/allocation/{index}'})
        except (ValueError,KeyError,TypeError) as exc:check['failure_reason']=str(exc)
        result['live_expired_allocation_checks'].append(check)
        atomic_json(ROOT/'identities.json',result)
        print('allocation',cid,allocation['vault_name'],check['status'],len(check['allocations']),flush=True)
    result['generated_at']=datetime.now(timezone.utc).isoformat()
    result['summary']={'pt_identities':len(result['markets']),
        'api_and_onchain_verified':sum(r['status']=='api_and_onchain_identity_verified' for r in result['markets']),
        'expired_identities':sum(r['expired_now'] for r in result['markets']),
        'reused_route_identities':sum(r['reused_route_linkage'] is not None for r in result['markets']),
        'live_vault_checks':len(result['live_expired_allocation_checks']),
        'positive_expired_allocation_rows':sum(float(a['vault_supply_position_usd'])>0 for c in result['live_expired_allocation_checks'] for a in c['allocations'])}
    atomic_json(ROOT/'identities.json',result)
    print(result['summary'])

if __name__=='__main__':main()
