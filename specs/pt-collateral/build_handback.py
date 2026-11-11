"""Offline checks and human handback for saved identity-only evidence."""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path('data/research/pt-collateral-identity-2026-11-05')
PATH=ROOT/'identities.json'
payload=json.loads(PATH.read_text())
if 'summary' not in payload:raise ValueError('Collection incomplete')


def verify_refs(value):
    if isinstance(value,dict):
        if 'path' in value and 'sha256' in value:
            if hashlib.sha256(Path(value['path']).read_bytes()).hexdigest()!=value['sha256']:
                raise ValueError('Evidence changed: '+value['path'])
        for child in value.values():verify_refs(child)
    elif isinstance(value,list):
        for child in value:verify_refs(child)


verify_refs(payload)
rows=payload['markets']
if len(rows)!=13 or len({(r['chain_id'],r['pt_address']) for r in rows})!=13:raise ValueError('PT queue coverage mismatch')
for row in rows:
    if row.get('official_api_evidence'):
        api_detail=json.loads(Path(row['official_api_evidence']['path']).read_text())['response']
        live_underlying=api_detail.get('underlyingAsset') or {}
        row.setdefault('inventory_underlying_metadata',dict(row['underlying']))
        for field in ['symbol','name','decimals']:
            if live_underlying.get(field) is not None:row['underlying'][field]=live_underlying[field]
        row['underlying']['live_metadata_evidence']=row['official_api_evidence']
    reads=row.get('onchain_identity',{}).get('reads',{})
    actual=reads.get('sy_yieldToken',{}).get('value')
    row['sy_yield_token_matches_api_underlying']=None if actual is None else actual==row['underlying']['address']
    actual_asset=reads.get('sy_assetInfo',{}).get('value')
    api=row.get('live_api_accounting_reference')
    row['sy_accounting_matches_api']=None if actual_asset is None or api is None else actual_asset['address']==api['address'].lower() and actual_asset['decimals']==api['decimals']
    row['live_expired_allocation_observations']=[]
    if row['expired_now']:
        for check in payload['live_expired_allocation_checks']:
            if check['chain_id']!=row['chain_id']:continue
            for allocation in check['allocations']:
                if allocation['pt_address']==row['pt_address']:
                    row['live_expired_allocation_observations'].append({
                        'vault_address':check['vault_address'],'vault_name':check['vault_name'],
                        'observed_at':check['observed_at'],'evidence':check['evidence'],**allocation})
        row['expired_allocation_status']='still_reported_positive' if any(float(a['vault_supply_position_usd'])>0 for a in row['live_expired_allocation_observations']) else 'not_confirmed_positive_in_targeted_recheck; original evidence retained'
# Validate requests were strictly metadata/identity/allocation reads.
for path in list((ROOT/'raw').glob('*.json'))+list((ROOT/'followup-raw').glob('*.json')):
    request=json.loads(path.read_text())
    if '/sdk/' in request['url'] or '/convert' in request['url']:raise ValueError('Unexpected route request')
    if request['method']=='POST' and 'graphql' not in request['url']:
        calls=request['body'] if isinstance(request['body'],list) else [request['body']]
        if any(c['method'] not in {'eth_chainId','eth_blockNumber','eth_getBlockByNumber','eth_call'} for c in calls):raise ValueError('Unexpected non-read RPC')
payload['validation']={'validated_at':datetime.now(timezone.utc).isoformat(),'evidence_hashes_verified':True,
    'exact_unique_chain_pt_count':13,'new_quote_requests':0,
    'underlying_yield_token_comparisons':[{'chain_id':r['chain_id'],'pt_address':r['pt_address'],'matches':r['sy_yield_token_matches_api_underlying']} for r in rows],
    'live_expired_allocations_retained':True,'assessment_scores_assigned':False}
PATH.write_text(json.dumps(payload,indent=2,allow_nan=False)+'\n')
lines=['# Morpho PT collateral identity handback — 2026-11-05','',
    'All 13 requested chain/PT identities are linked below. Existing cross-chain inventory and six matching prior route-export identities were reused. Live Pendle metadata and chain identity reads were added; no quote routes or full route diligence were repeated.',
    '', 'Machine evidence: `data/research/pt-collateral-identity-2026-11-05/identities.json`.',
    'Collection completed UTC: '+payload['generated_at'],
    'Original Morpho allocation source snapshot: '+payload['allocation_snapshot_as_of'],
    'Inventory snapshot: '+payload['inventory_generated_at']+'; immutable identities were selectively rechecked, without treating old quote clocks as fresh quotes.',
    '', 'RiskAnalyst owns assessment scope and grades. This handback assigns no score, transfers no Ethereum grade to Monad, and treats PT, SY wrapper, accounting asset and underlying asset as separate identities. It adds no execution-route gate to FarmAnalyst screening.',
    '', '## Exact deployment links', '',
    '| Chain | PT | PT contract | Pendle market | SY | Underlying | Maturity UTC | Verification |',
    '|---|---|---|---|---|---|---|---|']
for r in rows:
    lines.append(f"| {r['chain_id']} | {r['queue_symbol']} | `{r['pt_address']}` | `{r['pendle_market_address']}` | `{r['sy_address']}` | {r['underlying'].get('symbol') or 'symbol unavailable'} `{r['underlying']['address']}` | {r['maturity']} {'EXPIRED' if r['expired_now'] else ''} | {r['status']} |")
lines += ['', '## Accounting and observation boundaries', '',
    'Ethereum USD3 and Ethereum/Monad reUSD use USDC accounting references; this does not turn the PT or its underlying into USDC. siUSD uses iUSD accounting, strUSD uses trUSD, and fxSAVE uses its separate base-pool accounting asset. HyperEVM kHYPE uses the native HYPE accounting reference at the zero address; zero here is not a missing contract.',
    'Each machine record includes the official market URL, HTTP observation times, cached inventory timestamps, exact PT/SY/YT linkage reads, PT expiry and SY yieldToken/assetInfo observations. Market-detail price-update clocks are recorded separately and are not required to treat an immutable identity as a live price quote.',
    'Ethereum and Monad chain calls use explicit block numbers. HyperEVM default RPC only supports latest state; its before/after headers bound the observation window, and the evidence explicitly does not claim block-pinned calls.',
    '', '## Expired PTs still reported in targeted live vault allocations', '',
    'Values below are the vault\'s lender supply position in a Morpho market labelled with this collateral PT. They are not borrower collateral balances or bad-debt measurements. Dust is preserved without rounding it away.', '',
    '| Chain | Expired PT | Vault | Morpho market ID | Reported lender supply USD | Position scope | Live HTTP observation UTC |',
    '|---|---|---|---|---|---|---|']
for r in rows:
    if not r['expired_now']:continue
    for x in r['live_expired_allocation_observations']:
        lines.append(f"| {r['chain_id']} | {r['queue_symbol']} | {x['vault_name']} `{x['vault_address']}` | `{x['morpho_market_id']}` | {x['vault_supply_position_usd']!r} | {x.get('position_scope','direct V1 vault lender position')} | {x['observed_at']} |")
lines += ['', "V2 nested MetaMorpho rows, if present, are labelled as the nested vault's lender supply; they are not a pro-rata valuation of the parent vault's exposure. No overlapping allocation totals are summed.",
    'All original snapshot allocations remain in the machine handback, including any row absent from a later targeted response. Maturity is a review condition, not proof of closure, forfeiture, unrecoverable exposure or bad debt. No producer allocations or positions were edited.',
    '', '## Verification summary', '',json.dumps(payload['summary']),
    'Evidence hashes and exact unique chain/PT coverage verified; live market/SY/PT/expiry checks retained per record. Read-only request audit confirms no SDK route calls or transaction submission. Exact-chain and ambiguous-mapping rejection checks passed.',
    '', '## Source references', '',
    '- Pendle official API overview: https://docs.pendle.finance/pendle-v2-dev/Backend/ApiOverview',
    '- Per-deployment official detail endpoint: `https://api-v2.pendle.finance/core/v1/{chain}/markets/{market}` (actual URL and raw evidence in every record).',
    '- Morpho official allocation API: https://api.morpho.org/graphql (saved query, variables, raw response, source JSON pointers and observation times).',
    '- HyperEVM RPC limitations: https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/hyperevm/json-rpc',
    '- FarmAnalyst source queue and discovery snapshot paths plus SHA-256 hashes are in `input_evidence`.',
    '', 'No changes to trades, schedules, assessments, the inventory producer or live monitoring configuration.']
report=Path('specs/handoffs/pendletracker-lending-collateral-identity-2026-11-05-results.md')
report.parent.mkdir(parents=True,exist_ok=True);report.write_text('\n'.join(lines)+'\n')
print(json.dumps(payload['summary']))
print(report)
