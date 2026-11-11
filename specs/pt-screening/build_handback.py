"""Offline source-bound screening availability handback; no collection or publication."""
import hashlib
import json
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path('data/research/pt-screening-availability-2026-11-05')
p=json.loads((ROOT/'availability.json').read_text())
if 'summary' not in p:raise ValueError('Collection is incomplete')
if p['summary']['requested_leads']!=8 or p['summary']['lead_onchain_verified']!=8 or p['missing_requested_leads']:
 raise ValueError('Requested mapping coverage incomplete')
registry=json.loads((ROOT/'tori-registry-evidence.json').read_text())
if not all(registry['document_contains'].values()):raise ValueError('Tori documented identities absent')
p['tori_official_registry']=registry
p['coordination']=json.loads((ROOT/'coordination.json').read_text())
if (ROOT/'wrapper-source-references.json').exists():p['wrapper_source_references']=json.loads((ROOT/'wrapper-source-references.json').read_text())
e=p['monad_strusd_identity_resolution']
canonical=e['canonical_documented_strUSD'];reference=e['directory_reference']
reads=e['reads'];sy_token=e['sy_yieldToken'].get('value')
inputs=e['sy_tokensIn'].get('value',[]);outputs=e['sy_tokensOut'].get('value',[])
if (reads.get(reference,{}).get('code_present') is True and reads.get(canonical,{}).get('code_present') is True
    and sy_token==reference and canonical in inputs and canonical in outputs
    and e.get('wrapper_identity_getters',{}).get('rawToken()',{}).get('value')==canonical):
 e['status']='resolved_deployed_decimals_wrapper'
 e['finding']='The directory underlying is a deployed strUSD decimals wrapper, not the documented base token. Its rawToken() identifies the exact documented Monad strUSD. The SY yieldToken is the wrapper, while accepted deposit/output token identities are the documented base strUSD. Keep the wrapper, base token and trUSD accounting reference distinct; no Ethereum or parent grade is inherited.'
elif (reads.get(reference,{}).get('code_present') is False and reads.get(canonical,{}).get('code_present') is True
    and sy_token==canonical and canonical in inputs and canonical in outputs):
 e['status']='resolved_metadata_reference_vs_deployed_token'
 e['finding']='The directory underlying is a non-deployed scaled-18 accounting/display reference on Monad. The SY yieldToken and accepted deposit/output token identify documented Monad strUSD at the canonical address. These addresses are not interchangeable deployed tokens; do not assign a new wrapper or Ethereum grade by the metadata ticker.'
else:
 e['status']='unresolved_or_partial_identity_collision'
 e['finding']='Preserve distinct directory and documented addresses. Current evidence does not establish an exact alias/conversion relationship; no grade inheritance.'
e['boundary']='Identity only; no deposit/redeem simulation, sized quote, bridge route, backing verification or risk assessment.'
for r in p['markets']:
 r['retirement_status']='not_established; expired is a time classification and does not prove deactivation, closure or absence of exposure'
 if r['is_requested_lead']:
  r['sy_actual_yield_token']=r['onchain']['reads']['sy_yieldToken'].get('value')
  r['sy_accounting_observation']=r['onchain']['reads']['sy_assetInfo'].get('value')
  r['onchain_deposit_token_identities']=r['onchain']['reads']['sy_tokensIn'].get('value')
  r['onchain_output_token_identities']=r['onchain']['reads']['sy_tokensOut'].get('value')
 r['risk_assessment_status']='not_assigned; exact risk scope remains RiskAnalyst-owned'
refs=[]
def check_refs(v):
 if isinstance(v,dict):
  if 'path' in v and 'sha256' in v:
   assert hashlib.sha256(Path(v['path']).read_bytes()).hexdigest()==v['sha256'],v['path']
   refs.append(v['path'])
  for x in v.values():check_refs(x)
 elif isinstance(v,list):
  for x in v:check_refs(x)
check_refs(p)
for path in list((ROOT/'raw').glob('*.json'))+list((ROOT/'strusd-wrapper-raw').glob('*.json')):
 d=json.loads(path.read_text())
 assert '/sdk/' not in d['url'] and '/convert' not in d['url']
 if d['method']=='POST':
  calls=d['body'] if isinstance(d['body'],list) else [d['body']]
  assert all(c['method'] in ['eth_chainId','eth_blockNumber','eth_getBlockByNumber','eth_call','eth_getCode'] for c in calls)
p['validation']={'validated_at':datetime.now(timezone.utc).isoformat(),'hash_references_checked':len(refs),
 'no_routes_or_quotes_requested':True,'risk_scores_assigned':False,'exact_requested_lead_count':8}
(ROOT/'availability.json').write_text(json.dumps(p,indent=2,allow_nan=False)+'\n')
Path('data/pendle_screening_availability_latest.json').write_text(json.dumps(p,indent=2,allow_nan=False)+'\n')
lines=['# PT screening availability and mapping handback — 2026-11-05','',
 'Both requested handoffs were forwarded to the verified DeFiAnalyst, BM and SecurityAnalyst sessions; server acceptance is recorded in the machine evidence. These are ongoing owner commissions, not claims that their research is already complete.',
 '', '## PendleTracker source return','',
 'Refreshed the official directory with pagination checks; reused the earlier inventory and RiskAnalyst discovery as inputs. Completed live detail and on-chain identity verification for all eight requested leads, without collecting quotes or assigning grades.',
 'Directory collection completed UTC: '+p['directory']['completed_at'],
 'Mapping collection completed UTC: '+p['generated_at'],
 'Summary: '+json.dumps(p['summary']),
 'Machine evidence: `data/research/pt-screening-availability-2026-11-05/availability.json`.',
 'Consumer copy: `data/pendle_screening_availability_latest.json`. Both point to the same dated raw request evidence. No recurring producer or schedule was installed.',
 '', '## Requested unexpired deployments','',
 '| Chain | Family | PT | Market | SY | Directory underlying | Actual SY yield token | Accounting reference | Maturity UTC | Reported listing flags |',
 '|---|---|---|---|---|---|---|---|---|---|']
for r in p['markets']:
 if not r['is_requested_lead']:continue
 flags=r.get('listing_flags',{})
 display=f"active={flags.get('isActive')}, pro={flags.get('isWhitelistedPro')}, simple={flags.get('isWhitelistedSimple')}"
 lines.append(f"| {r['chain_id']} | {r['family_label']} | `{r['pt']['address']}` | `{r['market_address']}` | `{r['sy']['address']}` | `{r['directory_underlying']['address']}` | `{r.get('sy_actual_yield_token')}` | `{r['accounting_reference']['address']}` | {r['maturity']} | {display} |")
lines += ['', 'Flags are official metadata only. Directory presence, future expiry, indexed liquidity and active/listed labels do not prove trading enabled, holder access, executable capacity or a future redemption payout. No November4 rates or liquidity values were reused as current opportunities. All eight requested market/SY/PT/expiry identities are checked at explicit source blocks, with HTTP/source clocks preserved separately.',
 '', '## Monad strUSD identity discrepancy','',e['status']+': '+e['finding'],
 'Directory reference: `'+reference+'`; documented Monad token: `'+canonical+'`; actual SY yieldToken: `'+str(sy_token)+'`.',
 'Canonical token decimals: '+str(e['canonical_decimals'].get('value'))+'. Wrapper getter observations: '+str({k:v.get('value',v.get('status')) for k,v in e.get('wrapper_identity_getters',{}).items()})+'. On-chain SY token lists, code-presence checks and the current official Tori registry are saved as evidence. '+e['boundary'],
 '', '## Older related maturities retained','',
 '| Chain | Family | Market | Maturity UTC | Status |','|---|---|---|---|---|']
for r in p['markets']:
 if r['expired']:lines.append(f"| {r['chain_id']} | {r['family_label']} | `{r['market_address']}` | {r['maturity']} | Expired by time; delisting/retirement/exposure closure not established |")
lines += ['', 'In particular, old earnAUSD/AUSD October8 maturities and old sBOLD maturities are not substituted for the requested current markets. No old identity or exposure has been deleted.',
 '', '## Assessment boundaries and owner delivery','',
 '- DeFiAnalyst: existing earnAUSD commission, sBOLD/K3, Ethereum superUSDC and separately superWETH, and maintained Tori components. No duplicate underlying collection solely because a PT maturity changed.',
 '- BM: existing evidence reuse and missing financial screening evidence, prioritizing superUSDC and Tori; no new liquidity quotes.',
 '- SecurityAnalyst: bounded current authority/runtime/audit deltas and prior-evidence reuse for the exact deployments; no broad route work.',
 '- RiskAnalyst: underlying/wrapper assessment scope, dates and scores. Existing exact native Monad AUSD coverage is a consumer reference, not a newly assigned score or PT/wrapper assessment. Native AUSD is not its OFT adapter. Ethereum Tori registry tokens are not automatically identical to queue etrUSD or Monad representations. Superform Ethereum vaults are kept separate from Base products.',
 '', 'Owner message acceptance is recorded with thread IDs in `coordination.json`. The three owners were asked to return their evidence to RiskAnalyst. This handback supplies Pendle facts only.',
 '', '## Checks and sources','',
 'Validated pagination totals and uniqueness, exact requested chain/PT/SY/expiry identities, explicit source blocks, evidence hashes, expired maturity recomputation and read-only endpoint scope. No signer, portfolio monitor, DB update, transaction, quote, simulation, new job or publication.',
 '- [Pendle API overview](https://docs.pendle.finance/pendle-v2-dev/Backend/ApiOverview)',
 '- [Official Tori contract registry](https://docs.tori.finance/resources/contracts)',
 '- Exact official directory/detail URLs, RPC reads, raw data and request/source clocks are included in the machine evidence.']
report=Path('specs/handoffs/pt-screening-availability-pendletracker-2026-11-05-results.md');report.write_text('\n'.join(lines)+'\n')
print(json.dumps(p['summary']));print('strUSD:',e['status']);print(report)
