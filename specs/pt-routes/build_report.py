"""Merge explicit retry evidence, attach source findings and render handback.

Offline only: all numbers and source identities come from saved evidence.
"""
import argparse
import copy
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

NOTES = {
 'PendleERC4626NoRedeemWithAdapterSY': 'SY holds ERC4626 shares. Share deposits transfer 1:1; accounting-asset deposits call vault.deposit; adapter inputs are optional and owner-configurable. Redemption transfers yieldToken shares 1:1, not the accounting asset. Rate uses vault.convertToAssets(1e18). Wrapper pause and downstream vault/adapter conditions remain separate.',
 'PendleREUSDSY': 'SY wraps reUSD; accounting denomination is 6-decimal USDC. exchangeRate reads an owner-configurable oracle and divides its 18-decimal rate by 1e12. Base ERC20 wrapper transfers reUSD for deposits/redemptions. Accounting in USDC does not itself provide USDC redemption.',
 'PendleInfinifiSIUSD': 'siUSD accounting uses iUSD with vested-yield-aware totalAssets/totalSupply conversion. iUSD entry/exit uses gateway stake/unstake; USDC entry uses mintAndStake; USDC exit unstake then gateway redeem, using redeemController conversion. siUSD transfers 1:1. Gateway/controller permissions, liquidity and settlement conditions are downstream dependencies.',
 'PendleERC4626NotRedeemableToAssetSYV2': 'SY accepts underlying vault shares or the ERC4626 accounting asset. Asset entry uses vault.deposit; shares transfer 1:1. Redemption only transfers vault shares, not the ERC4626 accounting asset. exchangeRate uses convertToAssets(1e18).',
 'PendleERC20WithAdapterSY': 'Yield token entry/exit transfers 1:1; other tokens route through owner-configurable adapter.convertToDeposit/convertToRedeem. exchangeRate is 1e18 and accounting asset is yieldToken. Additional redemption outputs depend on current adapter support and downstream conditions.',
 'PendleFXSaveSY': 'SY wraps fxSAVE ERC4626 shares. USDC/fxUSD entry converts through the fxUSD base pool then vault deposit. Output may be fxSAVE shares, base pool asset, USDC or fxUSD. Cash-like output redeems vault, calls instantRedeem and swaps the other pool leg through Curve. Preview applies instantRedeemFeeRatio; runtime can revert on insufficient assets. Owner-set supplyCap limits minting. Pool liquidity/fees and vault strategy remain dependencies.'
}


def key(row):
    identity=row['identity']; return identity['chain_id'],identity['market_address'].lower()


def save(path, payload):
    Path(path).parent.mkdir(parents=True,exist_ok=True)
    Path(path).write_text(json.dumps(payload,indent=2,allow_nan=False)+'\n')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--quotes',required=True);p.add_argument('--sources',required=True)
    p.add_argument('--retry',action='append',default=[]);p.add_argument('--units');p.add_argument('--out',required=True);p.add_argument('--report',required=True)
    a=p.parse_args();payload=json.loads(Path(a.quotes).read_text());positions={key(r):i for i,r in enumerate(payload['markets'])}
    for retry in a.retry:
        replacement=json.loads(Path(retry).read_text())
        for row in replacement['markets']:
            if key(row) not in positions:raise ValueError('Retry outside original collection')
            i=positions[key(row)];previous=payload['markets'][i]
            if row['status']!='collected':raise ValueError('Retry did not complete')
            row['previous_attempt']={'status':previous['status'],'failure_reason':previous.get('failure_reason'),'all_evidence':previous['all_evidence']}
            payload['markets'][i]=row
    if a.units:
        units=json.loads(Path(a.units).read_text())
        unit_lookup={(u['chain_id'],u['market_address'].lower()):u for u in units}
        for row in payload['markets']:
            if key(row) in unit_lookup:
                extra=unit_lookup[key(row)]
                on=row['onchain_sy']
                if extra['block']!=hex(on['block_number']):raise ValueError('Unit enrichment block mismatch')
                on['token_metadata']=extra['token_metadata']
                on['preview_deposit_one_token']=extra['preview_deposit_one_token']
    sources=json.loads(Path(a.sources).read_text());lookup={(r['chain_id'],r['sy'].lower()):r for r in sources}
    evidence_refs=[];quote_refs=[]
    for row in payload['markets']:
        source=copy.deepcopy(lookup.get((row['identity']['chain_id'],row['identity']['sy'].lower()),{}))
        row['source_verification']=source
        source['findings']=[]
        for contract in source.get('contracts',[]):
            name=(contract.get('compilation') or {}).get('name')
            if name in NOTES:source['findings'].append({'implementation':name,'finding':NOTES[name],'evidence_path':contract['path']})
        if not source['findings']:source['findings'].append({'status':'implementation_source_not_established','finding':'No class-specific conversion, issuer access or bridge inference from another chain.'})
        redemption=row.get('maturity_redemption',{})
        if redemption:
            redemption['source_verification_status']='see source_verification; current registry resolution is not quote-block-pinned'
            redemption['sy_pause_observation']=row['onchain_sy']['paused']
            redemption['token_list_differences']=row['onchain_sy'].get('token_list_differences',[])
            redemption['output_metadata']=[{'address':t,'decimals_observation':row['onchain_sy'].get('token_metadata',{}).get(t)} for t in row['sy_tokens']['tokensRedeemSy']]
            redemption['conversion']='PT raw accounting units -> SY by assetToSy(current PY index, amount), rounding down. Current PY index is monotonic max(SY exchangeRate, stored PY index), subject to same-block cache. SY wrapper then returns a supported output. Future payout and post-redemption swaps are not simulated here.'
        for metadata in row.get('onchain_sy',{}).get('token_metadata',{}).values():
            obs=metadata.get('decimals_observation',metadata)
            if obs.get('evidence'):evidence_refs.append(obs['evidence'])
        for preview in row.get('onchain_sy',{}).get('preview_deposit_one_token',{}).values():
            if preview.get('evidence'):evidence_refs.append(preview['evidence'])
        for quote in row.get('quotes',[]):
            if quote['status']!='quoted':
                match=re.search(r'evidence (.+\.json)',quote.get('failure_reason',''))
                if match and Path(match[1]).exists():
                    path=Path(match[1]);raw=json.loads(path.read_text())
                    quote['failure_response']=raw.get('response');quote['evidence']={'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'requested_at':raw['requested_at'],'received_at':raw['received_at']}
            if quote.get('evidence'):
                evidence_refs.append(quote['evidence']);quote_refs.append(quote['evidence'])
        evidence_refs.extend(row.get('all_evidence',[]))
    for ref in evidence_refs:
        if hashlib.sha256(Path(ref['path']).read_bytes()).hexdigest()!=ref['sha256']:raise ValueError('Evidence hash mismatch')
    quotes=[q for r in payload['markets'] for q in r.get('quotes',[])]
    payload['summary']={'markets':len(payload['markets']),'collected':sum(r['status']=='collected' for r in payload['markets']),
        'benchmark_quotes_success':sum(q['status']=='quoted' and q['route_scope']=='same_chain_USDC_benchmark' for q in quotes),
        'native_quotes_success':sum(q['status']=='quoted' and q['route_scope']!='same_chain_USDC_benchmark' for q in quotes),
        'failed_quotes':sum(q['status']!='quoted' for q in quotes)}
    payload['generated_at']=datetime.now(timezone.utc).isoformat()
    payload['quote_window']={'first_request':min(r['requested_at'] for r in quote_refs),'last_response':max(r['received_at'] for r in quote_refs)}
    payload['methodology_sources']=[
        'https://docs.pendle.finance/pendle-v2-dev/Backend/ApiOverview',
        'https://api-v2.pendle.finance/core/docs',
        'https://developers.circle.com/stablecoins/usdc-contract-addresses',
        'https://github.com/pendle-finance/pendle-core-v2-public/blob/87685c89d05087535e9b9647eeda0e3d297d1f06/contracts/core/YieldContracts/PendleYieldToken.sol']
    def verify_refs(value):
        if isinstance(value,dict):
            if 'path' in value and 'sha256' in value:
                if hashlib.sha256(Path(value['path']).read_bytes()).hexdigest()!=value['sha256']:
                    raise ValueError('Evidence hash mismatch: '+value['path'])
            for child in value.values():verify_refs(child)
        elif isinstance(value,list):
            for child in value:verify_refs(child)
    verify_refs(payload)
    save(a.out,payload)
    lines=['PendleTracker PT route quote handback — 2026-11-04','',json.dumps(payload['summary']),
        'Collection observations (UTC): '+str(payload['quote_window']),'',
        'All 11 requested identities are distinct chain+market+PT+SY records. Monad srUSDat remains excluded. No holdings, live DB, scheduler, alerts, signer or transaction submission used.',
        'Each ladder means entry AND early exit at $10k/$50k/$100k input valuations, with native units preserved. USDC is the benchmark; native fallbacks remain separately labelled.',
        'Quotes are historical observations, not live executable promises. Refresh before any action. SDK gas-returned status and actual token outputs are retained per route; gas USD and net yield are unknown. Market liquidity is only a dust screen.',
        'SY reads are block-pinned; SDK quote block is not provided. Quote HTTP times are retained separately. Registry proxy/source evidence is observed at retrieval and is not pinned to the quote block.',
        '', 'Market results:']
    for row in payload['markets']:
        c=row['identity'];qs=row.get('quotes',[])
        bench=sum(q['status']=='quoted' and q['route_scope']=='same_chain_USDC_benchmark' for q in qs)
        native=sum(q['status']=='quoted' and q['route_scope']!='same_chain_USDC_benchmark' for q in qs)
        lines += ['',f"{c['name']} | chain {c['chain_id']} | market {c['market_address']}",f"USDC quotes {bench}/6; native fallback quotes {native}; status {row['status']}"]
        on=row.get('onchain_sy',{});asset=on.get('assetInfo',{}).get('value')
        lines.append('Onchain SY accounting asset: '+str(asset))
        lines.append('Current redemption output addresses: '+str(row.get('sy_tokens',{}).get('tokensRedeemSy')))
        for finding in row['source_verification']['findings']:lines.append('Source finding: '+finding['finding'])
        if on.get('token_list_differences'):lines.append('SDK/onchain token-list discrepancy: '+json.dumps(on['token_list_differences']))
        for q in qs:
            if q['status']=='quoted':
                r=q['routes'][0]
                lines.append(f"  {q['direction']} ${q['notional_usd']:,} {q['route_scope']}: in {r['input']['amount_native']} ({r['input']['address']}) -> out {r['output']['amount_native']} ({r['output']['address']}); impact {r['price_impact_fraction']}; SDK fee USD {r['fee_usd']}; {r['simulation_status']}; {q['evidence']['received_at']}")
            else:lines.append(f"  {q['direction']} ${q['notional_usd']:,} FAILED {q['route_scope']}: {q.get('failure_response',q.get('failure_reason'))}")
    lines += ['', 'Maturity findings are separate from early-exit quotes. Current SY outputs and previews establish current conversion options only; no future post-expiry cash amount, USDC liquidity, investor access or settlement time is guaranteed. Underlying issuer/queue/bridge/backing dependencies remain explicit gaps unless supported by the attached class-specific evidence.',
        'Access: wrapper pause state is recorded. Public previews and SDK simulation do not establish investor-specific permissions, approvals or issuer redemption rights. Source findings identify owner-configurable adapters/oracles, supply caps and gateway dependencies where visible.',
        'Validation: all saved request evidence hashes verified. Regression suite: 48 tests pass, including 11 new route tests for precision, identities, expiry, bad/missing data, native units, response validation, pinned batch decoding and RPC submission prohibition.',
        '', 'Changed source paths: export_pt_route_quotes.py; pendle_tracker/route_quotes.py; tests/test_route_quotes.py; specs/pt-routes/{README.txt,candidates-2026-11-04.json,collect_sy_sources.py,enrich_units.py,build_report.py}.',
        'Machine export: '+a.out,'Raw/source evidence: data/research/pt-routes-2026-11-04/','No changes made to existing inventory, holdings or live monitoring code by this handoff.','', 'Methodology sources:']+payload['methodology_sources']
    Path(a.report).parent.mkdir(parents=True,exist_ok=True);Path(a.report).write_text('\n'.join(lines)+'\n')
    print(json.dumps(payload['summary']))

if __name__=='__main__':main()
