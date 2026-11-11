"""Bounded research-only PT route evidence. No holdings, database, signer or sends.

POST is used only on Pendle's hosted calldata/quote endpoint. All RPC calls are
allowlisted reads. SDK quote success does not establish a wallet's permissions,
funding, approvals or future maturity-redemption terms.
"""
import fcntl
import hashlib
import json
import os
import time
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN, InvalidOperation, localcontext
from pathlib import Path

import requests

from .pt_inventory import contract, expiry_utc

BASE = 'https://api-v2.pendle.finance/core'
RECEIVER = '0x000000000000000000000000000000000000dead'
RPC = {1: 'https://ethereum-rpc.publicnode.com', 143: 'https://rpc.monad.xyz',
       42161: 'https://arb1.arbitrum.io/rpc'}
USDC = {1: '0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48',
        143: '0x754704bc059f8c67012fed69bc8a327a5aafb603',
        42161: '0xaf88d065e77c8cc2239327c5edb3a432268e5831'}
SELECTORS = {'assetInfo': 'a40bee50', 'exchangeRate': '3ba0b9a9',
             'getTokensIn': '213cae63', 'getTokensOut': '071bc3c9',
             'yieldToken': '76d5de85', 'pyIndexStored': 'd2a3584e',
             'decimals': '313ce567', 'paused': '5c975abb',
             'previewRedeem': 'cbe52ae3', 'previewDeposit': 'b8f82b26',
             'readTokens': '2c8ce6bc', 'expiry': 'e184c9be'}


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(payload, indent=2, allow_nan=False) + '\n')
    os.replace(temporary, path)


def size_raw(notional, price, decimals):
    if isinstance(decimals, bool) or not isinstance(decimals, int) or not 0 <= decimals <= 36:
        raise ValueError('Invalid token decimals')
    price = Decimal(str(price)); notional = Decimal(str(notional))
    if not price.is_finite() or price <= 0 or not notional.is_finite() or notional <= 0:
        raise ValueError('Invalid USD sizing inputs')
    with localcontext() as context:
        context.prec = 100
        raw = int((notional / price * Decimal(10) ** decimals).to_integral_value(rounding=ROUND_DOWN))
    if raw <= 0:
        raise ValueError('USD size rounds to zero')
    return raw


def fresh(value, max_hours=24):
    try:
        age = (datetime.now(timezone.utc) - expiry_utc(value)).total_seconds() / 3600
        return -5 / 60 <= age <= max_hours
    except (ValueError, TypeError, OverflowError):
        return False


def validate_identity(candidate, inventory, detail):
    cid = candidate['chain_id']; market = contract(candidate['market_address'])
    if int(detail['chainId']) != cid or contract(detail['address']) != market:
        raise ValueError('Live market identity mismatch')
    if inventory['chain_id'] != cid or contract(inventory['market_address']) != market:
        raise ValueError('Inventory identity mismatch')
    for key, field in [('pt', 'pt'), ('sy', 'sy'), ('underlying', 'underlyingAsset')]:
        expected = contract(candidate[key])
        if contract(inventory['tokens'][key]['address']) != expected:
            raise ValueError('Inventory ' + key + ' mismatch')
        token = detail[field]
        if contract(token['address']) != expected or int(token['chainId']) != cid:
            raise ValueError('Live ' + key + ' mismatch')
    if expiry_utc(inventory['maturity']) != expiry_utc(detail['expiry']):
        raise ValueError('Expiry mismatch')
    if expiry_utc(detail['expiry']) <= datetime.now(timezone.utc):
        raise ValueError('Matured candidate: early entry/exit pilot skipped')
    if not fresh(detail.get('dataUpdatedAt')) or detail.get('isActive') is not True:
        raise ValueError('Live market stale, future or inactive')


class EvidenceClient:
    """One shared process lock plus spacing for the whole pilot, including RPC.

    Only one named aggregator is enabled. Headers provide authoritative CU
    feedback; stop on weekly exhaustion and respect server minute reset/429.
    """
    def __init__(self, raw_dir, interval=3.0):
        self.raw_dir = Path(raw_dir); self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.session = requests.Session(); self.interval = max(3.0, interval)
        self.last = 0; self.not_before = 0; self.sequence = 0
        self.evidence = []

    def request(self, method, url, *, params=None, body=None):
        for attempt in range(3):
            time.sleep(max(0, self.last + self.interval - time.monotonic(), self.not_before - time.time()))
            self.last = time.monotonic(); self.sequence += 1
            stamp = now_iso()
            record = {'requested_at': stamp, 'method': method, 'url': url, 'params': params, 'body': body}
            try:
                response = self.session.request(method, url, params=params, json=body, timeout=120)
                record.update(received_at=now_iso(), http_status=response.status_code,
                              rate_headers={k: v for k, v in response.headers.items()
                                            if k.lower().startswith(('x-rate', 'x-computing'))})
                try:
                    record['response'] = response.json()
                except ValueError:
                    record['response'] = {'unparsed_text': response.text[:3000]}
                remaining = response.headers.get('x-ratelimit-remaining')
                if remaining is not None and float(remaining) < 25:
                    self.not_before = float(response.headers.get('x-ratelimit-reset', time.time() + 60)) + 1
                weekly = response.headers.get('x-ratelimit-weekly-remaining')
                exhausted = weekly is not None and float(weekly) < 25
            except requests.RequestException as exc:
                record.update(received_at=now_iso(), error_type=type(exc).__name__)
                response = None; exhausted = False
            path = self.raw_dir / f'{self.sequence:04d}.json'
            atomic_json(path, record)
            reference = {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                         'requested_at': stamp, 'received_at': record['received_at']}
            self.evidence.append(reference)
            if exhausted:
                raise ValueError('Weekly API budget exhausted; pilot stopped')
            if response is not None and response.status_code == 429 and attempt < 2:
                self.not_before = max(self.not_before, time.time() + 15 * (2 ** attempt))
                continue
            if response is None or not response.ok:
                response_body = record.get('response')
                reason = response_body.get('message', record.get('error_type', 'request failed')) if isinstance(response_body, dict) else response_body
                raise ValueError(f'HTTP {record.get("http_status", "transport_error")}: ' + str(reason)[:400] + f'; evidence {path}')
            return record['response'], reference
        raise ValueError('Rate limited')

    def get(self, path, params=None):
        return self.request('GET', BASE + path, params=params)

    def rpc(self, cid, method, params):
        if method not in {'eth_chainId', 'eth_blockNumber', 'eth_getBlockByNumber', 'eth_call'}:
            raise ValueError('Non-read RPC prohibited')
        payload, ref = self.request('POST', RPC[cid], body={'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params})
        if 'error' in payload or not payload.get('result'):
            raise ValueError('RPC returned error; evidence ' + ref['path'])
        return payload['result'], ref


def words(result):
    data = bytes.fromhex(result.removeprefix('0x'))
    if len(data) % 32 or not data:
        raise ValueError('Invalid ABI return')
    return [data[i:i+32] for i in range(0, len(data), 32)]


def decode(result, kind):
    data = words(result)
    if kind in ('getTokensIn', 'getTokensOut'):
        offset = int.from_bytes(data[0], 'big') // 32
        length = int.from_bytes(data[offset], 'big')
        if length > 100 or len(data) < offset + 1 + length:
            raise ValueError('Invalid ABI array')
        return ['0x' + x[-20:].hex() for x in data[offset+1:offset+1+length]]
    if kind == 'assetInfo':
        if len(data) != 3:
            raise ValueError('Invalid assetInfo')
        return {'asset_type': int.from_bytes(data[0], 'big'), 'address': '0x' + data[1][-20:].hex(),
                'decimals': int.from_bytes(data[2], 'big')}
    if kind == 'readTokens':
        if len(data) != 3:
            raise ValueError('Invalid market token tuple')
        return ['0x' + x[-20:].hex() for x in data]
    if kind == 'yieldToken':
        return '0x' + data[0][-20:].hex()
    return str(int.from_bytes(data[0], 'big'))


def read_call(client, cid, address, kind, block, argument=''):
    try:
        result, ref = client.rpc(cid, 'eth_call', [{'to': address, 'data': '0x' + SELECTORS[kind] + argument}, block])
        return {'status': 'read', 'value': decode(result, kind), 'block': block, 'evidence': ref}
    except (ValueError, KeyError, IndexError) as exc:
        return {'status': 'unknown_or_reverted', 'reason': str(exc), 'block': block}


def read_batch(client, cid, calls, block):
    body = [{'jsonrpc': '2.0', 'id': i + 1, 'method': 'eth_call',
             'params': [{'to': addr, 'data': '0x' + SELECTORS[kind] + argument}, block]}
            for i, (addr, kind, argument) in enumerate(calls)]
    payload, ref = client.request('POST', RPC[cid], body=body)
    if not isinstance(payload, list):
        # Some providers disallow batches. Keep the same pinned block on fallback.
        return [read_call(client, cid, a, k, block, arg) for a, k, arg in calls]
    ids = [r.get('id') for r in payload]
    if set(ids) != set(range(1, len(calls) + 1)) or len(ids) != len(calls):
        raise ValueError('Missing/duplicate RPC batch response IDs')
    by_id = {r['id']: r for r in payload}
    results = []
    for i, (_, kind, _) in enumerate(calls):
        row = by_id[i + 1]
        try:
            if 'error' in row:
                raise ValueError('RPC call reverted')
            results.append({'status': 'read', 'value': decode(row['result'], kind),
                            'block': block, 'evidence': ref, 'batch_response_id': i + 1})
        except (KeyError, ValueError, IndexError) as exc:
            results.append({'status': 'unknown_or_reverted', 'reason': str(exc),
                            'block': block, 'evidence': ref, 'batch_response_id': i + 1})
    return results


def sy_evidence(client, candidate, detail, token_lists):
    cid = candidate['chain_id']; sy = candidate['sy']
    actual_chain, _ = client.rpc(cid, 'eth_chainId', [])
    if int(actual_chain, 16) != cid:
        raise ValueError('RPC chain mismatch')
    block, _ = client.rpc(cid, 'eth_blockNumber', [])
    header, ref = client.rpc(cid, 'eth_getBlockByNumber', [block, False])
    result = {'block_number': int(block, 16), 'block_hash': header['hash'],
              'block_timestamp': int(header['timestamp'], 16), 'block_evidence': ref}
    if header.get('number') != block or not fresh(int(header['timestamp'], 16), max_hours=1):
        raise ValueError('Stale or mismatched RPC block')
    names = ['market_tokens', 'expiry', 'assetInfo', 'exchangeRate', 'getTokensIn',
             'getTokensOut', 'yieldToken', 'paused', 'decimals', 'pyIndexStored', 'benchmark_decimals']
    calls = [(candidate['market_address'], 'readTokens', ''), (candidate['pt'], 'expiry', '')]
    calls += [(sy, k, '') for k in names[2:9]]
    calls += [(detail['yt']['address'], 'pyIndexStored', ''), (USDC[cid], 'decimals', '')]
    result.update(dict(zip(names, read_batch(client, cid, calls, block))))
    if result['benchmark_decimals'].get('value') != '6':
        raise ValueError('Benchmark USDC decimals not verified')
    expected = [contract(sy), contract(candidate['pt']), contract(detail['yt']['address'])]
    if result['market_tokens'].get('value') != expected:
        raise ValueError('Onchain market SY/PT/YT mismatch or unavailable')
    if result['expiry'].get('value') != str(int(expiry_utc(detail['expiry']).timestamp())):
        raise ValueError('Onchain PT expiry mismatch or unavailable')
    result['token_list_differences'] = []
    for name, field in [('getTokensIn', 'tokensMintSy'), ('getTokensOut', 'tokensRedeemSy')]:
        if result[name].get('status') == 'read' and set(result[name]['value']) != {contract(t) for t in token_lists[field]}:
            result['token_list_differences'].append({'field': field, 'onchain': result[name]['value'], 'sdk': token_lists[field]})
    if result['assetInfo'].get('status') == 'read':
        asset = result['assetInfo']['value']
        acct = detail['accountingAsset']
        result['accounting_matches_api'] = (asset['address'] == contract(acct['address']) and asset['decimals'] == acct['decimals'])
    token_lists = dict(token_lists)
    for name, field in [('getTokensIn', 'tokensMintSy'), ('getTokensOut', 'tokensRedeemSy')]:
        if result[name].get('status') == 'read':
            token_lists[field] = result[name]['value']
    result['effective_token_lists'] = {k: token_lists[k] for k in ['tokensMintSy', 'tokensRedeemSy']}
    # A 1-SY preview is current conversion evidence, not a future PT payout promise.
    decimals = int(result['decimals'].get('value', detail['sy']['decimals']))
    redeem = token_lists['tokensRedeemSy']; mint = token_lists['tokensMintSy']
    all_tokens = sorted({contract(t) for t in redeem + mint})
    decimal_reads = read_batch(client, cid, [(t, 'decimals', '') for t in all_tokens], block)
    result['token_metadata'] = {t: {'decimals_observation': obs} for t, obs in zip(all_tokens, decimal_reads)}
    calls = []
    for token in redeem:
        arg = contract(token)[2:].zfill(64) + hex(10 ** decimals)[2:].zfill(64)
        calls.append((sy, 'previewRedeem', arg))
    mint_metadata = {}
    for token in mint:
        observation = result['token_metadata'][contract(token)]['decimals_observation']
        if observation['status'] == 'read':
            input_decimals = int(observation['value'])
            if not 0 <= input_decimals <= 36:
                raise ValueError('Invalid onchain deposit token decimals')
            mint_metadata[contract(token)] = input_decimals
            arg = contract(token)[2:].zfill(64) + hex(10 ** input_decimals)[2:].zfill(64)
            calls.append((sy, 'previewDeposit', arg))
    previews = read_batch(client, cid, calls, block) if calls else []
    result['preview_redeem_one_sy'] = dict(zip([contract(t) for t in redeem], previews[:len(redeem)]))
    result['preview_deposit_one_token'] = dict(zip(mint_metadata, previews[len(redeem):]))
    result['preview_units'] = 'redeem: 1 whole SY in, raw output units; deposit: 1 whole input token in, raw SY units'
    return result


def normalize_quote(payload, token_in, token_out, amount_raw, in_decimals, out_decimals):
    if payload.get('action') != 'swap':
        raise ValueError('Unexpected Convert action')
    actual_inputs = payload.get('inputs', [])
    if len(actual_inputs) != 1 or contract(actual_inputs[0]['token']) != contract(token_in) or int(actual_inputs[0]['amount']) != amount_raw:
        raise ValueError('Quote input mismatch')
    routes = []
    for route in payload.get('routes', []):
        output = route.get('outputs', [])
        if len(output) != 1 or contract(output[0]['token']) != contract(token_out) or int(output[0]['amount']) <= 0:
            raise ValueError('Quote output mismatch')
        tx = route['tx']; info = route['contractParamInfo']; data = route.get('data', {})
        params = dict(zip(info['contractCallParamsName'], info['contractCallParams']))
        if contract(params.get('receiver', RECEIVER)) != RECEIVER:
            raise ValueError('Unexpected quote receiver')
        routes.append({'input': {'address': contract(token_in), 'decimals': in_decimals,
                                  'amount_raw': str(amount_raw), 'amount_native': str(Decimal(amount_raw)/Decimal(10)**in_decimals)},
                       'output': {'address': contract(token_out), 'decimals': out_decimals,
                                   'amount_raw': output[0]['amount'], 'amount_native': str(Decimal(output[0]['amount'])/Decimal(10)**out_decimals)},
                       'router': contract(tx['to']), 'method': info['method'],
                       'price_impact_fraction': data.get('priceImpact'), 'price_impact_breakdown': data.get('priceImpactBreakDown'),
                       'fee_usd': (data.get('fee') or {}).get('usd'), 'fee_status': 'SDK reported; attribution retained in raw evidence' if data.get('fee') else 'unknown',
                       'aggregator': data.get('aggregatorType'), 'gas_used_simulated': data.get('gasUsed'),
                       'simulation_status': 'SDK simulation gas returned' if data.get('gasUsed') else 'quote/calldata only; simulation not confirmed',
                       'min_output_raw': params.get('minPtOut') or (params.get('output') or {}).get('minTokenOut'),
                       'gas_usd_status': 'unknown', 'net_yield_status': 'unknown',
                       'calldata_sha256': hashlib.sha256(tx['data'].encode()).hexdigest()})
    if not routes:
        raise ValueError('No successful routes')
    return routes


def collect_candidate(client, candidate, inventory):
    cid = candidate['chain_id']; market = candidate['market_address']
    result = {'identity': candidate, 'status': 'unverified', 'quotes': []}
    detail, detail_ref = client.get(f'/v1/{cid}/markets/{market}')
    validate_identity(candidate, inventory, detail)
    result.update(status='identity_verified', identity_evidence=detail_ref, maturity=detail['expiry'],
                  accounting_asset=detail['accountingAsset'], underlying_asset=detail['underlyingAsset'],
                  pt_implied_apy_fraction=detail.get('impliedApy'),
                  reported_market_liquidity_usd=(detail.get('liquidity') or {}).get('usd'),
                  liquidity_role='dust screen only; not executable capacity')
    tokens, ref = client.get(f'/v1/sdk/{cid}/markets/{market}/tokens')
    result['sy_tokens'] = tokens; result['sy_tokens_evidence'] = ref
    result['onchain_sy'] = sy_evidence(client, candidate, detail, tokens)
    result['maturity_redemption'] = {
        'status': 'current_SY_outputs_verified; future_PT_redemption_amount_not_simulated',
        'output_addresses': result['onchain_sy'].get('getTokensOut', {}).get('value', tokens['tokensRedeemSy']),
        'output_metadata': [{k: t.get(k) for k in ['address', 'symbol', 'decimals']}
                            for t in [detail['underlyingAsset'], detail['accountingAsset'], detail['sy']]
                            if contract(t['address']) in {contract(a) for a in tokens['tokensRedeemSy']}],
        'conversion': 'PT accounting raw units -> SY via assetToSy(PY index, PT amount), rounding down; PY index tracks max(SY exchange rate, stored PY index), subject to same-block cache. Post-expiry principal redemption uses the then-current PY index; SY -> output through wrapper preview/redeem. Current preview is not a guaranteed future payout.',
        'access_restrictions': 'unknown for an actual investor; public preview/quote does not prove allowlist, approvals, pause or issuer redemption access',
        'fees': 'future redemption fees unknown; current preview may embed conversion costs',
        'bridge_dependency': 'no bridge requested for same-chain quotes; issuer/backing bridge dependency not verified',
        'subsequent_benchmark_conversion': 'separate from maturity redemption; early exit USDC quote is not a future redemption quote'}
    result['maturity_redemption']['source_verification_status'] = 'separate source registry evidence required; not inferred from token lists'
    result['maturity_redemption']['sy_pause_observation'] = result['onchain_sy']['paused']
    result['maturity_redemption']['token_list_differences'] = result['onchain_sy'].get('token_list_differences', [])
    if result['onchain_sy'].get('getTokensOut', {}).get('status') != 'read':
        result['maturity_redemption']['status'] = 'SDK output list only; onchain outputs unverified'
    agg, _ = client.get(f'/v1/sdk/{cid}/supported-aggregators')
    supported = {r['name']: r.get('computingUnit') for r in agg.get('aggregators', [])}
    aggregator = 'kyberswap' if 'kyberswap' in supported and float(supported['kyberswap']) <= 5 else None
    benchmark = USDC[cid]
    ids = f'{cid}-{benchmark},{cid}-{candidate["pt"]}'
    prices, price_ref = client.get('/v1/prices/assets', {'ids': ids})
    if prices.get('errors'):
        raise ValueError('USD sizing price response has errors: ' + str(prices['errors'])[:300])
    price_map = prices.get('priceMap', prices.get('prices', {}))
    def usd_price(address):
        value = price_map.get(f'{cid}-{address}')
        if isinstance(value, dict):
            value = value.get('usd', value.get('price'))
        if value is None:
            raise ValueError('USD price unavailable for ' + address)
        return str(value)
    pt_price = usd_price(candidate['pt']); benchmark_price = usd_price(benchmark)
    pt_decimals = detail['pt']['decimals']
    for notional in [10000, 50000, 100000]:
        for direction in ['entry', 'early_exit']:
            incoming, outgoing, indec, outdec, price = ((benchmark, candidate['pt'], 6, pt_decimals, benchmark_price)
                if direction == 'entry' else (candidate['pt'], benchmark, pt_decimals, 6, pt_price))
            amount = size_raw(notional, price, indec)
            quote = {'direction': direction, 'notional_usd': notional, 'route_scope': 'same_chain_USDC_benchmark',
                     'valuation': {'source': '/v1/prices/assets', 'evidence': price_ref, 'input_usd_price': price,
                                   'source_update_clock': 'not provided; HTTP receipt only'},
                     'amount_in_raw': str(amount), 'input_address': incoming, 'output_address': outgoing,
                     'slippage_tolerance_fraction': 0.01, 'block_reference_status': 'SDK does not bind response to a block; surrounding RPC observation is not quote block',
                     'status': 'failed'}
            try:
                if aggregator is None:
                    raise ValueError('No low-CU benchmark aggregator available')
                if expiry_utc(detail['expiry']) <= datetime.now(timezone.utc):
                    raise ValueError('Market matured during collection')
                body = {'receiver': RECEIVER, 'slippage': 0.01, 'inputs': [{'token': incoming, 'amount': str(amount)}],
                        'outputs': [outgoing], 'enableAggregator': True, 'aggregators': [aggregator], 'useLimitOrder': False}
                payload, ref = client.request('POST', BASE + f'/v3/sdk/{cid}/convert', body=body)
                quote['evidence'] = ref
                quote['routes'] = normalize_quote(payload, incoming, outgoing, amount, indec, outdec)
                # Bind every quote's router call to the exact requested market.
                for route in payload['routes']:
                    info = route['contractParamInfo']; params = dict(zip(info['contractCallParamsName'], info['contractCallParams']))
                    if contract(params['market']) != contract(market):
                        raise ValueError('Quote market mismatch')
                quote['status'] = 'quoted'
            except (ValueError, KeyError, InvalidOperation) as exc:
                quote['failure_reason'] = str(exc)
            result['quotes'].append(quote)
            if quote['status'] == 'failed':
                native = detail['underlyingAsset']
                native_address = contract(native['address'])
                accepted = tokens['tokensMintSy'] if direction == 'entry' else tokens['tokensRedeemSy']
                fallback = {'direction': direction, 'notional_usd': notional,
                            'route_scope': 'native_underlying_fallback; not benchmark conversion', 'status': 'failed',
                            'block_reference_status': quote['block_reference_status']}
                try:
                    if native_address not in {contract(t) for t in accepted}:
                        raise ValueError('Underlying is not a direct SY input/output')
                    if not fresh(native.get('priceUpdatedAt'), max_hours=1):
                        raise ValueError('Native USD sizing price stale/missing')
                    native_price = str(native['price']['usd'])
                    incoming, outgoing, indec, outdec, price = ((native_address, candidate['pt'], native['decimals'], pt_decimals, native_price)
                        if direction == 'entry' else (candidate['pt'], native_address, pt_decimals, native['decimals'], pt_price))
                    amount = size_raw(notional, price, indec)
                    fallback['valuation'] = {'input_usd_price': price, 'source': 'live market detail' if direction == 'entry' else '/v1/prices/assets',
                                             'evidence': detail_ref if direction == 'entry' else price_ref}
                    fallback['amount_in_raw'] = str(amount)
                    payload, ref = client.request('POST', BASE + f'/v3/sdk/{cid}/convert', body={
                        'receiver': RECEIVER, 'slippage': 0.01, 'inputs': [{'token': incoming, 'amount': str(amount)}],
                        'outputs': [outgoing], 'enableAggregator': False, 'useLimitOrder': False})
                    fallback['evidence'] = ref
                    fallback['routes'] = normalize_quote(payload, incoming, outgoing, amount, indec, outdec)
                    for route in payload['routes']:
                        info = route['contractParamInfo']; params = dict(zip(info['contractCallParamsName'], info['contractCallParams']))
                        if contract(params['market']) != contract(market):
                            raise ValueError('Fallback market mismatch')
                    fallback['status'] = 'quoted'
                except (ValueError, KeyError, InvalidOperation) as exc:
                    fallback['failure_reason'] = str(exc)
                result['quotes'].append(fallback)
            print(f'{candidate["name"]} chain={cid} {direction} ${notional}: {quote["status"]}', flush=True)
    result['status'] = 'collected'
    return result


def export(inventory_path, manifest_path, output_path, raw_dir, max_markets=11, only_markets=None):
    if Path(output_path).resolve() in {Path(inventory_path).resolve(), Path(manifest_path).resolve(),
                                      Path('data/pendle_markets.json').resolve(), Path('data/pendle_index_latest.json').resolve()}:
        raise ValueError('Research output must not overwrite source/live artifacts')
    if list(Path(raw_dir).glob('*.json')):
        raise ValueError('Use an empty raw evidence directory to preserve prior evidence')
    inventory = json.loads(Path(inventory_path).read_text()); manifest = json.loads(Path(manifest_path).read_text())
    if not fresh(inventory.get('generated_at')):
        raise ValueError('Inventory export stale/future; refresh upstream inventory first')
    if not 1 <= max_markets <= 11:
        raise ValueError('Pilot limited to 1..11 exact candidates')
    lookup = {(r['chain_id'], contract(r['market_address'])): r for r in inventory['markets']}
    exclusions = {(r['chain_id'], contract(r['market_address'])) for r in manifest['excluded']}
    selected = manifest['candidates'][:max_markets]
    if only_markets:
        wanted = set(only_markets)
        selected = [r for r in manifest['candidates'] if f"{r['chain_id']}:{r['market_address']}" in wanted]
        if len(selected) != len(wanted) or len(selected) > max_markets:
            raise ValueError('Requested market outside exact pilot manifest or limit')
    if len({(r['chain_id'], contract(r['market_address'])) for r in selected}) != len(selected):
        raise ValueError('Duplicate candidate')
    if any((r['chain_id'], contract(r['market_address'])) in exclusions for r in selected):
        raise ValueError('Excluded market in pilot')
    result = {'schema_version': 1, 'collection_started_at': now_iso(), 'generated_at': None,
              'scope': 'read-only research quote pilot; not vetted recommendations or guaranteed execution',
              'inventory_generated_at': inventory['generated_at'], 'excluded': manifest['excluded'],
              'benchmark': 'same-chain native USDC; does not imply bridge/backing/access verification',
              'policy': {'notionals_usd': [10000, 50000, 100000], 'max_markets': max_markets,
                         'api_interval_seconds': 3, 'aggregators_per_request': 1, 'limit_orders': False,
                         'quote_validity': 'point-in-time only; refresh immediately before any execution',
                         'yield': 'PT implied APY alone; underlying yield, points and LP rewards excluded'},
              'markets': []}
    # Separate from cron/live DB locks; prevents simultaneous research pilots.
    with open('/tmp/pendle_route_quotes.lock', 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        client = EvidenceClient(raw_dir)
        for candidate in selected:
            before = len(client.evidence)
            try:
                inv = lookup[(candidate['chain_id'], contract(candidate['market_address']))]
                if not inv.get('inventory_quality_ok') or not fresh(inv.get('fetched_at')) or not fresh(inv.get('source_data_as_of')):
                    raise ValueError('Candidate inventory stale or quality failed')
                row = collect_candidate(client, candidate, inv)
            except (ValueError, KeyError, TypeError, InvalidOperation) as exc:
                row = {'identity': candidate, 'status': 'failed', 'failure_reason': str(exc), 'quotes': []}
                print(f'{candidate["name"]} chain={candidate["chain_id"]}: {exc}', flush=True)
            row['all_evidence'] = client.evidence[before:]
            result['markets'].append(row)
            result['generated_at'] = now_iso()
            result['summary'] = {'markets': len(result['markets']),
                                 'collected': sum(m['status'] == 'collected' for m in result['markets']),
                                 'quoted': sum(q['status'] == 'quoted' for m in result['markets'] for q in m['quotes']),
                                 'failed_quotes': sum(q['status'] != 'quoted' for m in result['markets'] for q in m['quotes'])}
            atomic_json(output_path, result)
    return result
