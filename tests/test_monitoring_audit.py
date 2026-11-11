import copy
import json
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

import pendle_risk_alerter as alert
import pendle_digest as digest
from pendle_tracker import portfolio as p


class CoverageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.feed = Path(self.tmp.name) / 'feed.json'
        self.cache = Path(self.tmp.name) / 'cache.json'
        self.old = dict(key='old', market='old_market', chain=1, exposure='direct')
        self.feed_data = dict(generated_at=datetime.now(timezone.utc).isoformat(),
                              upstream_generated_at=datetime.now(timezone.utc).isoformat(),
                              positions=[dict(chain=1, pt_token_address='0x1', value_usd=100)])
        self.index = {(1, '0x1'): dict(name='new', market_address='new_market', chain=1)}

    def resolve(self):
        self.feed.write_text(json.dumps(self.feed_data))
        with patch.object(p, 'DIRECT_CACHE_PATH', str(self.cache)), \
             patch.object(p, 'last_known_direct_watchlist', return_value=[self.old]), \
             patch.object(p, 'load_pt_index', return_value=self.index):
            return p.derive_direct_watchlist(str(self.feed), write_positions=False)

    def test_fresh_entry_and_exit(self):
        self.assertEqual([x['key'] for x in self.resolve()], ['new'])
        self.assertTrue(p.LAST_COVERAGE['complete'])
        self.feed_data['positions'] = []
        self.assertEqual(self.resolve(), [])
        self.assertEqual(p.LAST_COVERAGE['status'], 'verified_empty')

    def test_partial_retains_old(self):
        self.feed_data['positions'].append(dict(chain=1, pt_token_address='unknown'))
        self.assertEqual({x['key'] for x in self.resolve()}, {'new', 'old'})
        self.assertFalse(p.LAST_COVERAGE['complete'])

    def test_bad_source_clocks(self):
        for timestamp in [None, 'not-a-timestamp', (datetime.now(timezone.utc)-timedelta(days=3)).isoformat(),
                          (datetime.now(timezone.utc)+timedelta(days=1)).isoformat()]:
            self.feed_data['generated_at'] = timestamp
            self.assertEqual(self.resolve(), [self.old])
            self.assertFalse(p.LAST_COVERAGE['complete'])

    def test_empty_skipped_is_not_zero(self):
        self.feed_data.update(positions=[], skipped_stale=['wallet'])
        self.assertEqual(self.resolve(), [self.old])
        self.assertFalse(p.LAST_COVERAGE['complete'])

    def test_missing_index_retains(self):
        self.index = {}
        self.assertEqual(self.resolve(), [self.old])
        self.assertEqual(p.LAST_COVERAGE['status'], 'missing_index')

    def test_missing_feed_retains(self):
        with patch.object(p, 'last_known_direct_watchlist', return_value=[self.old]):
            self.assertEqual(p.derive_direct_watchlist(str(self.feed), write_positions=False), [self.old])
            self.assertFalse(p.LAST_COVERAGE['complete'])

    def test_empty_cache_survives_restart(self):
        with patch.object(p, 'DIRECT_CACHE_PATH', str(self.cache)):
            p._save_direct_cache([])
            self.assertEqual(p.last_known_direct_watchlist(), [])


class AlertTests(unittest.TestCase):
    def run_alert(self, snap, state, send=True):
        with patch('sys.argv', ['alerter']), patch.object(alert, 'read_snapshot', return_value=snap), \
             patch.object(alert, 'read_history', return_value={}), \
             patch.object(alert, 'load_state', return_value=copy.deepcopy(state)), \
             patch.object(alert, 'send_telegram', return_value=send) as sender, \
             patch.object(alert, 'save_state') as saver:
            code = alert.main()
            return code, sender, saver

    def snap(self):
        return dict(generated_at=datetime.now(timezone.utc).isoformat(), holdings_coverage={'complete':True, 'status':'fresh'},
                    markets=[dict(key='PT-test', exposure='direct', days_to_maturity=-1, expired=True)])

    def test_failure_retry_success_no_duplicate(self):
        snap = self.snap()
        state = {'markets':{}, 'coverage_status':'fresh'}
        code, sender, saver = self.run_alert(snap, state, False)
        self.assertEqual(code, 1)
        self.assertEqual(saver.call_args.args[0]["markets"], {})
        self.assertEqual(saver.call_args.args[0]["pending_delivery"]["next"], 0)
        code, sender, saver = self.run_alert(snap, state)
        sender.assert_called_once()
        acknowledged = saver.call_args.args[0]
        code, sender, saver = self.run_alert(snap, acknowledged)
        sender.assert_not_called()

    def test_partial_delivery_resume(self):
        state = {"markets": {}, "pending_delivery": {
            "messages": ["first", "second"], "next": 0,
            "target_state": {"markets": {"acknowledged": {}}}}}
        with patch.object(alert, 'send_telegram', side_effect=[True, False]) as sender, \
             patch.object(alert, 'save_state'):
            self.assertEqual(alert.deliver_pending(state), 1)
        self.assertEqual(state['pending_delivery']['next'], 1)
        with patch.object(alert, 'send_telegram', return_value=True) as sender, \
             patch.object(alert, 'save_state') as saver:
            self.assertEqual(alert.deliver_pending(state), 0)
            sender.assert_called_once_with('second')
            self.assertEqual(saver.call_args.args[0]['markets'], {'acknowledged': {}})

    def test_incomplete_does_not_clear(self):
        snap = self.snap(); snap.update(markets=[], holdings_coverage={'complete':False})
        state = {'markets':{'old':{'near_maturity_status':'EXPIRED'}}, 'coverage_status':'unknown'}
        _, sender, saver = self.run_alert(snap, state)
        sender.assert_not_called()
        self.assertIn('old', saver.call_args.args[0]['markets'])

    def test_dependency_has_no_maturity_alert(self):
        snap = self.snap(); snap['markets'][0]['exposure']='dependency_review'
        _, sender, _ = self.run_alert(snap, {'markets':{}, 'coverage_status':'fresh'})
        sender.assert_not_called()

    def test_coverage_failure_is_alerted_once(self):
        snap = self.snap(); snap.update(markets=[], holdings_coverage={'complete':False, 'status':'missing_index'})
        _, sender, saver = self.run_alert(snap, {'markets':{}})
        self.assertIn('HOLDINGS COVERAGE', sender.call_args.args[0])
        _, sender, _ = self.run_alert(snap, saver.call_args.args[0])
        sender.assert_not_called()

    def test_wording(self):
        message = alert.format_message([dict(market='test',signal='near_maturity',kind='expired')])
        self.assertIn('PY-index/SY', message)
        self.assertNotIn('1:1', message)
        message = alert.format_message([dict(market='test',signal='near_maturity',kind='recovered')])
        self.assertIn('closure not established', message)

    def test_digest_same_day_membership(self):
        now = datetime.now(timezone.utc)
        feed = dict(generated_at=now.isoformat(), upstream_generated_at=now.isoformat(),
                    positions=[dict(symbol='PT-entered', chain=1, value_usd=100, wallet='test')])
        message = digest.render_digest(feed, {}, now, 0, 0)
        self.assertIn('PT-entered', message)
        feed['positions'] = []
        message = digest.render_digest(feed, {}, now, 0, 0)
        self.assertNotIn('PT-entered', message)
        self.assertIn('No direct PT positions', message)
        self.assertIn('srUSDat', message)

class DigestWarningTests(unittest.TestCase):
    def position(self, flags):
        position = dict(chain=1, pt_token_address='0xabc', value_usd=100, entry_apy=0.1)
        record = dict(key='PT-test', pt_implied_apy=10, flags=[{'code': code} for code in flags])
        return digest.build_position(position, {(1, '0xabc'): record}, datetime.now(timezone.utc))

    def test_yt_lp_context_does_not_warn_pt_holder(self):
        position = self.position(['yt_underwater', 'composition_drift'])
        self.assertEqual(position['flags'], [])
        self.assertEqual(digest._status_emoji(position), '🟢')
        self.assertNotIn('YT underwater', str(digest.render_detail(position, False)))
        self.assertEqual(position['market_context_flags'], ['yt_underwater', 'composition_drift'])

    def test_real_pt_warning_is_preserved(self):
        position = self.position(['yt_underwater', 'low_liquidity'])
        self.assertEqual(digest._status_emoji(position), '⚠️')
        self.assertEqual(position['flags'], ['low_liquidity'])

    def test_dependency_review_is_not_a_holdings_banner(self):
        now = datetime.now(timezone.utc)
        feed = dict(generated_at=now.isoformat(), upstream_generated_at=now.isoformat(), positions=[])
        text = digest.render_digest(feed, {(1, 'legacy'): {'dependency_review': {'status': 'unverified'}}}, now, 0, 0)
        self.assertNotIn('Legacy collateral', text)
        # Real source-coverage warnings still surface.
        feed['skipped_stale'] = ['wallet']
        self.assertIn('holdings coverage incomplete', digest.render_digest(feed, {}, now, 0, 0))


class AlertRoutingTests(unittest.TestCase):
    run_alert = AlertTests.run_alert
    snap = AlertTests.snap

    def test_alerter_uses_digest_route(self):
        from unittest.mock import mock_open
        data = json.dumps({'pendle_reporter': {'telegram': {'bot_token': 'test-token', 'chat_id': 'test-chat'}}})
        with patch('builtins.open', mock_open(read_data=data)):
            self.assertEqual(alert.load_telegram_creds(), ('test-token', 'test-chat'))

    def test_stale_unsent_outbox_recomputes_without_old_dependency_clears(self):
        snap = self.snap()
        snap['markets'] = [dict(key='legacy', exposure='dependency_review')]
        old = (datetime.now(timezone.utc)-timedelta(days=3)).isoformat()
        state = {'markets': {'legacy': {'near_maturity_status': 'EXPIRED'}},
                 'coverage_status': 'fresh', 'last_run_at': old,
                 'pending_delivery': {'messages': ['OLD NOTICE'], 'next': 0, 'target_state': {'markets': {}}}}
        _, sender, saver = self.run_alert(snap, state)
        sender.assert_not_called()
        self.assertNotIn('pending_delivery', saver.call_args.args[0])
        self.assertNotIn('legacy', saver.call_args.args[0]['markets'])

    def test_first_healthy_snapshot_is_not_a_warning(self):
        snap = self.snap(); snap['markets'] = []
        _, sender, saver = self.run_alert(snap, {'markets': {}})
        sender.assert_not_called()
        self.assertEqual(saver.call_args.args[0]['coverage_status'], 'fresh')

if __name__ == '__main__':
    unittest.main()
