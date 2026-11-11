"""Additional identity-only getters for Monad strUSD's decimals wrapper."""
import json,sys
from pathlib import Path
from Crypto.Hash import keccak
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from pendle_tracker.route_quotes import EvidenceClient,RPC,atomic_json
ROOT=Path('data/research/pt-screening-availability-2026-11-05')
p=json.loads((ROOT/'availability.json').read_text());e=p['monad_strusd_identity_resolution']
client=EvidenceClient(ROOT/'strusd-wrapper-raw')
if list((ROOT/'strusd-wrapper-raw').glob('*.json')):raise ValueError('Evidence already exists')
reads={}
for signature in ['rawToken()','rawDecimals()','decimals()']:
 h=keccak.new(digest_bits=256);h.update(signature.encode());selector='0x'+h.hexdigest()[:8]
 payload,ref=client.request('POST',RPC[143],body={'jsonrpc':'2.0','id':1,'method':'eth_call','params':[{'to':e['directory_reference'],'data':selector},e['block']]})
 row={'signature':signature,'evidence':ref,'block':e['block']}
 if payload.get('error'):row.update(status='unknown_or_reverted',error=payload['error'])
 else:
  raw=payload['result'];row.update(status='read',raw_result=raw,value='0x'+raw[-40:].lower() if signature=='rawToken()' else str(int(raw,16)))
 reads[signature]=row
 print(signature,row.get('value',row.get('status')),flush=True)
e['wrapper_identity_getters']=reads
atomic_json(ROOT/'availability.json',p)
