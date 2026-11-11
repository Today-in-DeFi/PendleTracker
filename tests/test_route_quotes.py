import copy
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, Mock

from pendle_tracker import route_quotes as q

A = '0x' + '1'*40
B = '0x' + '2'*40
C = '0x' + '3'*40
D = '0x' + '4'*40


class RouteTests(unittest.TestCase):
    def test_decimal_sizing(self):
        self.assertEqual(q.size_raw(10000, '1.25', 6), 8000000000)
        self.assertEqual(q.size_raw(10000, '2', 18), 5000*10**18)
        for value in ['NaN', 'Infinity', '0', '-1', None]:
            with self.assertRaises((ValueError, ArithmeticError)):
                q.size_raw(10000, value, 18)
        with self.assertRaises(ValueError):
            q.size_raw(10000, 1, True)

    def test_exact_chain_and_pt_identity(self):
        expiry=(datetime.now(timezone.utc)+timedelta(days=90)).isoformat()
        stamp=datetime.now(timezone.utc).isoformat()
        candidate=dict(chain_id=1,market_address=A,pt=B,sy=C,underlying=D)
        inv=dict(chain_id=1,market_address=A,maturity=expiry,
                 tokens={k:{'address':v} for k,v in [('pt',B),('sy',C),('underlying',D)]})
        detail=dict(chainId=1,address=A,expiry=expiry,dataUpdatedAt=stamp,isActive=True,
                    **{k:{'address':v,'chainId':1} for k,v in [('pt',B),('sy',C),('underlyingAsset',D)]})
        q.validate_identity(candidate,inv,detail)
        wrong=copy.deepcopy(detail);wrong['chainId']=143
        with self.assertRaises(ValueError):q.validate_identity(candidate,inv,wrong)
        wrong=copy.deepcopy(detail);wrong['pt']['address']=A
        with self.assertRaises(ValueError):q.validate_identity(candidate,inv,wrong)
        wrong=copy.deepcopy(detail);wrong['expiry']=(datetime.now(timezone.utc)-timedelta(days=1)).isoformat()
        with self.assertRaises(ValueError):q.validate_identity(candidate,inv,wrong)

    def test_freshness_fail_closed(self):
        self.assertFalse(q.fresh(None))
        self.assertFalse(q.fresh((datetime.now(timezone.utc)+timedelta(hours=1)).isoformat()))
        self.assertFalse(q.fresh((datetime.now(timezone.utc)-timedelta(days=2)).isoformat()))

    def payload(self):
        return dict(action='swap',inputs=[dict(token=A,amount='1000000')],routes=[{
            'outputs':[dict(token=B,amount='2000000000000000000')],
            'tx':{'to':C,'data':'0x1234'},
            'contractParamInfo':{'method':'swapExactTokenForPt',
                                 'contractCallParamsName':['receiver','market','minPtOut'],
                                 'contractCallParams':[q.RECEIVER,D,'1900000000000000000']},
            'data':{'priceImpact':-0.001,'fee':{'usd':0.2},'gasUsed':'100000'}}])

    def test_quotes_keep_native_units_and_fee(self):
        row=q.normalize_quote(self.payload(),A,B,1000000,6,18)[0]
        self.assertEqual(row['input']['amount_native'],'1')
        self.assertEqual(row['output']['amount_native'],'2')
        self.assertEqual(row['fee_usd'],0.2)
        self.assertEqual(row['gas_usd_status'],'unknown')
        self.assertNotIn('net_apy',row)

    def test_wrong_quote_tokens_or_input_rejected(self):
        for change in ['input','output','zero','action']:
            p=self.payload()
            if change=='input':p['inputs'][0]['amount']='1'
            if change=='output':p['routes'][0]['outputs'][0]['token']=C
            if change=='zero':p['routes'][0]['outputs'][0]['amount']='0'
            if change=='action':p['action']='redeem-py'
            with self.assertRaises(ValueError):q.normalize_quote(p,A,B,1000000,6,18)

    def test_batch_decodes_by_id_not_return_order(self):
        client=Mock()
        client.request.return_value=([
            {'id':2,'result':'0x'+hex(18)[2:].zfill(64)},
            {'id':1,'result':'0x'+hex(6)[2:].zfill(64)}], {'path':'fixture'})
        rows=q.read_batch(client,1,[(A,'decimals',''),(B,'decimals','')],'0x123')
        self.assertEqual([r['value'] for r in rows],['6','18'])
        sent=client.request.call_args.kwargs['body']
        self.assertTrue(all(r['method']=='eth_call' and r['params'][1]=='0x123' for r in sent))

    def test_duplicate_batch_response_rejected(self):
        client=Mock();client.request.return_value=([{'id':1,'result':'0x01'},{'id':1,'result':'0x01'}],{})
        with self.assertRaises(ValueError):q.read_batch(client,1,[(A,'decimals',''),(B,'decimals','')],'0x123')

    def test_failed_batch_call_does_not_become_zero(self):
        client=Mock();client.request.return_value=([{'id':1,'error':{'message':'reverted'}}],{'path':'fixture'})
        row=q.read_batch(client,1,[(A,'decimals','')],'0x123')[0]
        self.assertEqual(row['status'],'unknown_or_reverted')
        self.assertNotIn('value',row)

    def test_http_error_array_is_recorded_as_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            client=q.EvidenceClient(directory)
            response=Mock(status_code=403,ok=False,headers={})
            response.json.return_value=[{'error':{'message':'archive unavailable'}}]
            client.session.request=Mock(return_value=response)
            with self.assertRaisesRegex(ValueError,'archive unavailable'):
                client.request('POST',q.RPC[42161],body=[])

    def test_rpc_submission_prohibited(self):
        client=q.EvidenceClient('/tmp/pendle-route-test-raw')
        with self.assertRaises(ValueError):client.rpc(1,'eth_sendRawTransaction',['0xdead'])

    def test_abi_asset_and_array(self):
        word=lambda n:hex(n)[2:].zfill(64)
        result='0x'+word(0)+D[2:].zfill(64)+word(18)
        self.assertEqual(q.decode(result,'assetInfo'),{'asset_type':0,'address':D,'decimals':18})
        result='0x'+word(32)+word(1)+A[2:].zfill(64)
        self.assertEqual(q.decode(result,'getTokensOut'),[A])

if __name__=='__main__':unittest.main()
