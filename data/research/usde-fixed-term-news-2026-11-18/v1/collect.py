import sys,json
from pathlib import Path
from datetime import datetime,timezone
sys.path.insert(0,str(Path(__file__).resolve().parents[4]))
from pendle_tracker.route_quotes import EvidenceClient,expiry_utc
R=Path(__file__).resolve().parent;c=EvidenceClient(R/'raw')
cache=R.parents[1]/'srusdat-market-quotes-2026-11-18/v1/all-directory-raw';selected=[]
for f in sorted(cache.glob('*.json')):
 d=json.loads(f.read_text());p=d['response']
 for x in p.get('results',p.get('markets',[])):
  if x.get('name')=='USDe' and int(x['chainId'])==1 and expiry_utc(x['expiry']).year==2027:selected.append({'row':x,'cache_ref':str(f),'retrieved_at':d['received_at']})
assert len(selected)==4
old=json.loads((R.parents[2]/'pendle_pt_inventory_latest.json').read_text());ids={(x['chain_id'],x['market_address'].lower()) for x in old['markets']}
result={'version':'usde-fixed-term-news-v1','scope':'Four exactUSDe notsUSDe Ethereum fixed-term markets; reused full directorycache + bounded currentdetail/data/token-list reads. No new integration/jobs/quotes/holdings/trades.','existing_inventory_generated_at':old.get('generated_at'),'markets':[]}
for item in selected:
 x=item['row'];address=x['address'];detail,ref=c.get(f'/v1/1/markets/{address}');assert detail['address'].lower()==address.lower() and detail['underlyingAsset']['address'].lower()=='0x4c9edd5852cd905f086c759e8383e09bff1e68b3'
 data,dref=c.get(f'/v2/1/markets/{address}/data');tokens,tref=c.get(f'/v1/sdk/1/markets/{address}/tokens');row={'directory':item,'detail':detail,'detail_ref':ref,'current_data':data,'data_ref':dref,'SDK_tokens':tokens,'tokens_ref':tref,'in_existing_inventory':(1,address.lower()) in ids,'official_market_url':f'https://app.pendle.finance/trade/markets/{address}/swap'};result['markets'].append(row);print(address,x['expiry'],'oldinventory',row['in_existing_inventory'],'detailkeys',list(detail),'datakeys',list(data),flush=True)
(R/'return.json').write_text(json.dumps(result,indent=2)+'\n')
