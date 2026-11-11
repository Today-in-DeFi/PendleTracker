import copy
import json
from datetime import datetime,timezone,timedelta
from pathlib import Path
import unittest
from unittest.mock import Mock
from pendle_tracker.pt_inventory import PTInventoryClient,normalize_market,expiry_utc,assets_by_id,token_reference,discover,legacy_audit
from pendle_tracker.client import PendleAPIError

NOW=datetime(2026,11,4,10,5,tzinfo=timezone.utc)
FIXTURE=Path(__file__).parent/'fixtures/pt_inventory/market.json'


def live_fixture():
    d=json.loads(FIXTURE.read_text());d['detail']['dataUpdatedAt']='2026-11-04T09:59:00Z';return d


def normalize(d=None,**changes):
    d=d or live_fixture()
    return normalize_market(d['directory_market'],{},set(),NOW.isoformat(),now=NOW,detail=d['detail'],detail_fetched_at=NOW.isoformat(),**changes)


class InventoryTests(unittest.TestCase):
    def test_exact_expiry_parsing_units_and_timezone(self):
        target=datetime(2026,12,10,tzinfo=timezone.utc)
        for value in ['2026-12-10T00:00:00Z','2026-12-10T08:00:00+08:00',int(target.timestamp()),int(target.timestamp()*1000)]:
            self.assertEqual(expiry_utc(value),target)
        with self.assertRaises(ValueError):expiry_utc('2026-12-10T00:00:00')

    def test_real_payload_rate_money_units_and_accounting_reference(self):
        r=normalize()
        self.assertAlmostEqual(r['pt_implied_apy_pct'],8.002,places=3)
        self.assertAlmostEqual(r['reported_liquidity_usd'],769861.5460476149,places=4)
        self.assertEqual(r['tokens']['underlying']['symbol'],'NGI+')
        self.assertEqual(r['tokens']['accounting']['display_symbol'],'USDC')
        self.assertEqual(r['tokens']['accounting']['symbol'],'USDC-scaled18')
        self.assertIn('virtual',r['tokens']['accounting']['reference_kind'])
        self.assertEqual(r['risk_status'],'not_screened')
        self.assertTrue(r['inventory_quality_ok'],r['quality_issues'])

    def test_past_expiry_overrides_cached_active_flag(self):
        d=live_fixture();d['directory_market'].update(expiry='2024-10-31T00:00:00Z',expired=False,days_to_maturity=30)
        r=normalize_market(d['directory_market'],{},set(),NOW.isoformat(),now=NOW)
        self.assertTrue(r['expired']);self.assertLess(r['days_to_maturity'],0)
        self.assertEqual(r['maturity_state'],'expired')

    def test_seven_day_boundary(self):
        for delta,state in [(7,'unexpired_ge_7d'),(6.999,'near_maturity'),(0,'expired')]:
            d=live_fixture()['directory_market'];d['expiry']=(NOW+timedelta(days=delta)).isoformat()
            self.assertEqual(normalize_market(d,{},set(),NOW.isoformat(),now=NOW)['maturity_state'],state)

    def test_creation_timestamp_is_not_quote_freshness(self):
        r=normalize()
        self.assertTrue(r['source_row_timestamp'].startswith('2026-09'))
        self.assertEqual(r['freshness_status'],'source_timestamp_current')
        self.assertEqual(r['source_data_as_of'],'2026-11-04T09:59:00Z')

    def test_stale_and_future_upstream_quotes_are_held(self):
        for delta in [-25,1]:
            d=live_fixture();d['detail']['dataUpdatedAt']=(NOW+timedelta(hours=delta)).isoformat()
            r=normalize(d)
            self.assertFalse(r['inventory_quality_ok']);self.assertIn('upstream_quote_stale_or_future',r['quality_issues'])

    def test_missing_quote_clock_is_not_fresh(self):
        d=live_fixture();d['detail']['dataUpdatedAt']=None;r=normalize(d)
        self.assertIn('upstream_quote_timestamp_missing',r['quality_issues'])
        self.assertFalse(r['inventory_quality_ok'])

    def test_detail_identity_and_expiry_must_match_directory(self):
        for field,value in [('address','0x'+'9'*40),('expiry','2027-01-01T00:00:00Z')]:
            d=live_fixture();d['detail'][field]=value
            with self.assertRaises(ValueError):normalize(d)

    def test_lp_incentives_never_enter_pt_rate(self):
        d=live_fixture();d['detail'].update(aggregatedApy=99,pendleApy=88)
        self.assertAlmostEqual(normalize(d)['pt_implied_apy_pct'],8.002,places=3)

    def test_accounting_reference_can_be_canonical_cross_chain(self):
        issues=[];value='1-0x'+'1'*40
        token_reference(value,8453,{},set(),issues,'accounting')
        self.assertNotIn('accounting_chain_mismatch',issues)
        issues=[];token_reference(value,8453,{},set(),issues,'pt')
        self.assertIn('pt_chain_mismatch',issues)

    def test_invalid_quote_stays_unknown(self):
        d=live_fixture();d['detail']['impliedApy']='NaN';r=normalize(d)
        self.assertIsNone(r['pt_implied_apy_pct'])
        self.assertIn('impliedApy_invalid',r['quality_issues'])

    def test_asset_metadata_conflict_is_detected(self):
        a={'chainId':1,'address':'0x'+'1'*40,'symbol':'ONE','decimals':18}
        assets,conflicts=assets_by_id({'assets':[a,{**a,'symbol':'OTHER'}]})
        self.assertEqual(len(conflicts),1)

    def test_legacy_audit_recomputes_maturity(self):
        x={'generated_at':NOW.isoformat(),'chains':{'1':{'markets':{'0x'+'1'*40:{'maturity':'2024-01-01T00:00:00Z','expired':False,'days_to_maturity':10}}}}}
        r=legacy_audit(x,now=NOW)
        self.assertEqual(r['summary']['expired_flag_conflicts'],1)
        self.assertEqual(r['summary']['actual_unexpired_ge_7d'],0)
        self.assertEqual(r['summary']['missing_per_market_timestamp'],1)

    def client(self,pages):
        c=Mock();c.base='https://api-v2.pendle.finance/core'
        c.supported_chains.return_value={'chainIds':[1,56]};c.all_assets.return_value={'assets':[]}
        c.all_markets_page.side_effect=pages
        return c

    def old_market(self,n,chain=1):
        return {'chainId':chain,'address':'0x'+format(n,'040x'),'expiry':'2020-01-01T00:00:00Z','details':{}}

    def test_duplicate_market_across_pages_rejected(self):
        batch=[self.old_market(n) for n in range(1,101)]
        c=self.client([{'results':batch,'total':200,'skip':0,'limit':100},{'results':batch,'total':200,'skip':100,'limit':100}])
        with self.assertRaises(ValueError):discover(c,Mock(),now=NOW)

    def test_partial_pagination_rejected(self):
        c=self.client([{'results':[self.old_market(1)],'total':2,'skip':0,'limit':100},{'results':[],'total':2,'skip':1,'limit':100}])
        with self.assertRaises(ValueError):discover(c,Mock(),now=NOW)

    def test_same_contract_on_different_chains_stays_distinct(self):
        c=self.client([{'results':[self.old_market(1,1),self.old_market(1,56)],'total':2,'skip':0,'limit':100}])
        result=discover(c,Mock(),now=NOW)
        self.assertEqual(len({r['id'] for r in result['markets']}),2)
        self.assertEqual(result['summary']['by_maturity_state']['expired'],2)

    def test_api_limit_contract(self):
        c=PTInventoryClient()
        for skip,limit in [(-1,100),(0,101),(True,100),(0,False)]:
            with self.assertRaises(ValueError):c.all_markets_page(skip,limit)

class ProjectionTests(unittest.TestCase):
    def test_projection_recalculates_expiry_and_keeps_collection_clock(self):
        from unittest.mock import patch
        from pendle_tracker import index
        row=json.loads((FIXTURE.parent/'legacy_row.json').read_text())
        with patch.object(index,'_latest_index_rows',return_value=[row]):
            markets,last=index._project_chain_markets(1,now=NOW)
        item=markets[row['market_address']]
        self.assertTrue(item['expired']);self.assertLess(item['days_to_maturity'],-90)
        self.assertEqual(item['fetched_at'],'2026-07-29T10:00:00Z')
        self.assertEqual(item['freshness_status'],'snapshot_stale_or_future')
        self.assertIsNone(item['source_data_as_of'])

    def test_projection_does_not_turn_bad_expiry_into_active(self):
        from unittest.mock import patch
        from pendle_tracker import index
        row=json.loads((FIXTURE.parent/'legacy_row.json').read_text());row['maturity']='invalid'
        with patch.object(index,'_latest_index_rows',return_value=[row]):
            markets,last=index._project_chain_markets(1,now=NOW)
        self.assertIsNone(markets[row['market_address']]['expired'])
        self.assertEqual(markets[row['market_address']]['maturity_state'],'invalid_expiry')

    def test_no_rounding_to_premature_expiry(self):
        from pendle_tracker import index
        self.assertGreater(index._days_to_maturity((NOW+timedelta(seconds=1)).isoformat(),now=NOW),0)

class ConsumerTests(unittest.TestCase):
    def test_consumer_rechecks_expiry_instead_of_cached_days(self):
        from pendle_tracker.pt_inventory import current_inventory
        record=normalize();record.update(days_to_maturity=999,expired=False,maturity='2020-01-01T00:00:00Z')
        self.assertEqual(current_inventory({'generated_at':NOW.isoformat(),'markets':[record]},now=NOW)['count'],0)

    def test_consumer_rechecks_source_clock(self):
        from pendle_tracker.pt_inventory import current_inventory
        record=normalize();payload={'generated_at':NOW.isoformat(),'markets':[record]}
        self.assertEqual(current_inventory(payload,now=NOW)['count'],1)
        self.assertEqual(current_inventory(payload,now=NOW+timedelta(days=2))['count'],0)

    def test_feed_excludes_raw_payloads_and_keeps_quality_gaps(self):
        from pendle_tracker.pt_inventory import feed_projection
        result=feed_projection({'markets':[{'quality_issues':['gap']}],'raw_pages':[{'anything':1}],'legacy_audit':{'summary':{'count':1},'rows':[1]}})
        self.assertNotIn('raw_pages',result)
        self.assertNotIn('rows',result['legacy_audit'])
        self.assertEqual(result['markets'][0]['quality_issues'],['gap'])
