"""Final review: transport lifecycle, cutoff invariance and provider isolation."""
import base64
from copy import deepcopy
from datetime import timedelta
import json
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from forecast_cloud import ArchiveMissing
from forecast_journal import canonical
from market_archive import MarketArchive
from market_research import empty_state
from test_market_research import T, capture, observation, replay, settle


class FinalReviewTests(unittest.TestCase):
    def test_conflicting_odds_republications_never_choose_an_arbitrary_price(self):
        record = observation()
        other = deepcopy(record)
        other['source']['publisher'] = 'Redistributor'
        other['odds'][-1]['prices'] = {'home': 2.8, 'away': 1.5}
        for records in ([record, other], [other, record]):
            report = replay(settle(capture(empty_state(), records), record))
            self.assertEqual(report['test_n'], 0)
            self.assertEqual(report['exclusions']['conflicting_odds_at_same_time'], 1)

    def test_changed_market_outcomes_are_rejected_before_replay(self):
        record = observation()
        other = deepcopy(record)
        other['outcomes'] = ['home', 'draw']
        other['shares']['draw'] = other['shares'].pop('away')
        for s in other['odds']:
            s['prices']['draw'] = s['prices'].pop('away')
        with self.assertRaisesRegex(ValueError, 'Conflicting market outcomes'):
            capture(empty_state(), [record, other])

    def test_distinct_books_keep_their_own_prices_and_splits(self):
        record = observation()
        other = deepcopy(record)
        other['bookmaker'] = 'Circa'
        for s in [other['source']] + [o['source'] for o in other['odds']]:
            s['original_bookmaker'] = 'Circa'
            s['original_source'] = 'Circa splits'
        other['shares']['home']['handle'] = 20.
        other['shares']['away']['handle'] = 80.
        other['odds'][-1]['prices'] = {'home': 2.8, 'away': 1.5}
        report = replay(settle(capture(empty_state(), [record, other]), record))
        rows = {r['bookmaker']: r for r in report['rows']}
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows['DraftKings']['prices']['home'], 1.8)
        self.assertEqual(rows['Circa']['prices']['home'], 2.8)
        self.assertEqual(rows['DraftKings']['picks']['high_handle'], 'home')
        self.assertEqual(rows['Circa']['picks']['high_handle'], 'away')

    def test_cutoff_boundary_and_late_ingestion(self):
        record = observation()  # cutoff is T + 12h
        cutoff = T + timedelta(hours=12)
        for clock, expected in ((cutoff, 1), (cutoff + timedelta(microseconds=1), 0)):
            report = replay(settle(capture(empty_state(), [record], clock), record))
            self.assertEqual(report['test_n'], expected)
        initial = settle(capture(empty_state(), [record]), record)
        frozen = replay(initial)['rows']
        later = observation(at=cutoff + timedelta(microseconds=1),
                            kickoff=T + timedelta(days=1))
        later['odds'][-1]['prices'] = {'home': 5., 'away': 1.2}
        later['news'][0]['text'] = 'Later information'
        self.assertEqual(replay(capture(initial, [later], cutoff + timedelta(seconds=1)))['rows'], frozen)


class ArchiveLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.cloud = MarketArchive('secret-test-token', 'owner/private')
        self.meta = {'private': True, 'default_branch': 'main'}

    def test_first_initialization_existing_branch_and_roundtrip(self):
        for branch_exists in (True, False):
            responses = [self.meta, self.meta, ArchiveMissing('missing'),
                         {} if branch_exists else ArchiveMissing('missing')]
            if not branch_exists:
                responses += [{'object': {'sha': 'default-head'}}, {'ref': 'refs/heads/market-research'}]
            responses += [{'commit': {'sha': 'initialized'}}]
            with patch.object(self.cloud, '_request', side_effect=responses) as req:
                state = self.cloud.initialize()
            put = req.call_args.args
            self.assertEqual(put[0], 'PUT')
            self.assertNotIn('sha', put[2])
            self.assertEqual(put[2]['branch'], 'market-research')
            self.assertEqual(json.loads(base64.b64decode(put[2]['content'])), empty_state())
            encoded = {'encoding': 'base64', 'sha': 'file-sha', 'content': put[2]['content']}
            with patch.object(self.cloud, '_request', side_effect=[self.meta, encoded]):
                self.assertEqual(self.cloud.load(), (state, 'file-sha'))

    def test_initialization_failures_never_reset_or_retry(self):
        for failure in (ValueError('corrupt'), ValueError('network failure')):
            with patch.object(self.cloud, '_request', side_effect=[self.meta, self.meta, failure]) as req:
                with self.assertRaises(ValueError):
                    self.cloud.initialize()
                self.assertEqual(req.call_count, 3)
        with patch.object(self.cloud, '_request', side_effect=[self.meta, self.meta,
                          ArchiveMissing('missing'), {}, {}]) as req:
            with self.assertRaisesRegex(ValueError, 'not acknowledged'):
                self.cloud.initialize()
            self.assertEqual(req.call_count, 5)

    def test_real_transport_maps_errors_without_leaking_token_or_retrying(self):
        failures = [URLError('secret-test-token'), TimeoutError('secret-test-token')]
        failures += [HTTPError(self.cloud.endpoint, code, 'secret-test-token', {}, None)
                     for code in (403, 404, 409, 422, 500)]
        for failure in failures:
            opener = unittest.mock.Mock()
            opener.open.side_effect = failure
            with patch('forecast_cloud.build_opener', return_value=opener):
                with self.assertRaises(ValueError) as raised:
                    self.cloud._request('PUT', self.cloud.endpoint, {'branch': self.cloud.branch})
            self.assertNotIn('secret-test-token', str(raised.exception))
            self.assertEqual(opener.open.call_count, 1)
            self.assertEqual(isinstance(raised.exception, ArchiveMissing),
                             isinstance(failure, HTTPError) and failure.code == 404)

    def test_uncertain_write_can_be_reloaded_without_duplicate_retry(self):
        state = capture(empty_state(), [observation()])
        encoded = lambda s: {'encoding': 'base64', 'sha': 'sha',
                            'content': base64.b64encode(canonical(s).encode()).decode()}
        with patch.object(self.cloud, '_request', side_effect=[self.meta, encoded(empty_state()),
                          ValueError('uncertain write'), self.meta, encoded(state)]) as req:
            with self.assertRaises(ValueError):
                self.cloud.change(lambda _: state)
            self.assertEqual(self.cloud.load()[0], state)
            self.assertEqual(sum(c.args[0] == 'PUT' for c in req.call_args_list), 1)
