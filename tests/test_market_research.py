"""Synthetic research evidence only; no real money/fixtures or external API calls."""
import base64
from copy import deepcopy
import csv
from datetime import datetime, timedelta, timezone
import io
import json
import unittest
from unittest.mock import patch

from forecast_cloud import ArchiveMissing, GitHubArchive
from forecast_journal import canonical
from market_archive import MarketArchive
from market_backtest import backtest
from market_research import (append_observations, append_protocol, append_result,
                             available, decimal_odds, delta_pp, empty_state,
                             normalize_prices, parse_csv, source_status, validate_state)

T = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)


def source(at=T, **changes):
    return {'publisher': 'VSiN', 'original_source': 'DraftKings splits',
            'original_bookmaker': 'DraftKings', 'url': 'https://example.com/original',
            'published_at': at.isoformat(), 'observed_at': at.isoformat(),
            'original_text': 'Synthetic test reference; no real market claim',
            'verification': 'manual_verified', 'permission': 'manual_reference',
            'fetch_status': 'manual', **changes}


def observation(identity='fixture-1', at=T, kickoff=None):
    kickoff = kickoff or at + timedelta(days=1)
    return {'fixture_id': identity, 'sport': 'football', 'home': 'A', 'away': 'B',
            'market': 'moneyline', 'line': 'none', 'bookmaker': 'DraftKings',
            'kickoff': kickoff.isoformat(), 'outcomes': ['home', 'away'], 'source': source(at),
            'shares': {'home': {'tickets': 40., 'tickets_origin': 'reported',
                                'handle': 70., 'handle_origin': 'reported'},
                       'away': {'tickets': 60., 'tickets_origin': 'reported',
                                'handle': 30., 'handle_origin': 'reported'}},
            'odds': [{'at': (at - timedelta(hours=1)).isoformat(), 'kind': 'opening',
                      'prices': {'home': 2.2, 'away': 1.8}, 'source': source(at - timedelta(hours=1))},
                     {'at': at.isoformat(), 'kind': 'snapshot',
                      'prices': {'home': 1.8, 'away': 2.2}, 'source': source(at)}],
            'news': [{'kind': 'lineup', 'certainty': 'fact', 'text': 'Synthetic lineup note', 'source': source(at)}],
            'hypothesis': 'Synthetic research hypothesis', 'explanation': ''}


def capture(state, records, clock=T):
    with patch('market_research.now', return_value=clock):
        return append_observations(state, records)


def settle(state, record, at=None, **changes):
    kickoff = datetime.fromisoformat(record['kickoff'])
    at = at or kickoff + timedelta(hours=3)
    data = {k: record[k] for k in ('sport', 'fixture_id', 'market', 'line')}
    data.update(actual_kickoff=record['kickoff'], ended_at=(kickoff + timedelta(hours=2)).isoformat(),
                score='1–0', settlement={'home': 'win', 'away': 'loss'}, confirmed=True,
                source_url='https://example.com/result', explanation='Synthetic completed result')
    data.update(changes)
    with patch('market_research.now', return_value=at):
        return append_result(state, data)


def replay(state, **kw):
    params = {'test_start': '2026-01-02T00:00:00Z', 'test_end': '2026-02-01T00:00:00Z'}
    params.update(kw)
    with patch('market_backtest.now', return_value=T + timedelta(days=40)):
        return backtest(state, **params)


class MarketEvidenceTests(unittest.TestCase):
    def test_decimal_and_margin_normalization(self):
        self.assertEqual(decimal_odds(-200, 'american'), 1.5)
        self.assertEqual(decimal_odds(150, 'american'), 2.5)
        prices, fair, margin = normalize_prices({'a': 2, 'b': 2, 'draw': 4})
        self.assertEqual(fair, {'a': .4, 'b': .4, 'draw': .2})
        self.assertEqual(margin, .25)
        for v in (1, 0, float('nan'), float('inf'), True):
            with self.assertRaises((ValueError, TypeError)):
                decimal_odds(v)
        with self.assertRaises(ValueError):
            decimal_odds(99, 'american')
        with self.assertRaises(ValueError):
            normalize_prices({'one_side_only': 2})

    def test_exact_percentages_and_complement_provenance(self):
        record = observation()
        record['shares']['home']['handle'] = 70.25
        record['shares']['away']['handle'] = 29.75
        record['shares']['away']['handle_origin'] = 'calculated_complement'
        state = capture(empty_state(), [record])
        share = state['observations'][0]['payload']['shares']['home']
        self.assertEqual(delta_pp(share), 30.25)
        self.assertEqual(record['odds'][0]['prices']['home'], 2.2)  # caller untouched
        record['shares']['away']['handle'] = 30
        with self.assertRaises(ValueError):
            capture(empty_state(), [record])

    def test_missing_handle_is_not_invented_and_unverified_unavailable(self):
        record = observation()
        for share in record['shares'].values():
            share['handle'] = None; share['handle_origin'] = 'unavailable'
        state = capture(empty_state(), [record])
        self.assertIsNone(delta_pp(state['observations'][0]['payload']['shares']['home']))
        result = replay(settle(state, record))
        self.assertEqual(result['test']['high_handle']['bets'], 0)
        self.assertEqual(result['test']['gap']['bets'], 0)
        self.assertEqual(result['test']['baseline']['bets'], 1)
        record['source']['verification'] = 'unverified'
        state = capture(empty_state(), [record])
        self.assertFalse(available(state['observations'][0]['payload']))
        self.assertEqual(source_status(state['observations'][0]['payload'], T), 'nem elérhető')

    def test_source_origin_and_permissions(self):
        record = observation()
        record['source']['original_bookmaker'] = 'Circa'
        with self.assertRaises(ValueError):
            capture(empty_state(), [record])
        record = observation(); record['source']['permission'] = 'licensed_api'
        with self.assertRaises(KeyError):
            capture(empty_state(), [record])
        record['source']['license_url'] = 'https://example.com/license'
        self.assertTrue(capture(empty_state(), [record]))
        for key, value in [('fetch_status', 'error'), ('permission', 'denied')]:
            record = observation(); record['source'][key] = value
            state = capture(empty_state(), [record])
            self.assertFalse(available(state['observations'][0]['payload']))

    def test_atomic_import_and_csv_limits(self):
        record = observation(); invalid = observation('bad'); invalid['home'] = invalid['away']
        original = empty_state()
        with self.assertRaises(ValueError):
            capture(original, [record, invalid])
        self.assertEqual(original, empty_state())
        stream = io.StringIO(); writer = csv.writer(stream)
        writer.writerow(['observation_json']); writer.writerow([json.dumps(record)])
        self.assertEqual(parse_csv(stream.getvalue().encode()), [record])
        for raw in (b'wrong\n{}\n', b'observation_json\n', b'x' * (2*1024*1024+1)):
            with self.assertRaises(ValueError):
                parse_csv(raw)
        with self.assertRaises(ValueError):
            capture(original, [record] * 501)

    def test_server_recorded_time_cannot_be_imported_or_backdated(self):
        record = observation(); record['recorded_at'] = T.isoformat()
        with self.assertRaises(ValueError):
            capture(empty_state(), [record])
        record = observation()
        state = capture(empty_state(), [record], T + timedelta(days=2))
        self.assertFalse(state['observations'][0]['payload']['prospective'])
        self.assertEqual(replay(settle(state, record, T + timedelta(days=3)))['test_n'], 0)
        state = capture(empty_state(), [observation()])
        with self.assertRaises(ValueError):
            capture(state, [observation('earlier', T-timedelta(days=1))], T-timedelta(days=1))

    def test_tamper_and_append_only_results(self):
        record = observation(); state = capture(empty_state(), [record])
        original = canonical(state['observations'])
        state = settle(state, record)
        state = settle(state, record, at=T + timedelta(days=2),
                       settlement={'home': 'loss', 'away': 'win'}, explanation='Correction')
        self.assertEqual(canonical(state['observations']), original)
        self.assertEqual(len(state['results']), 2)
        self.assertEqual(replay(state)['test']['high_handle']['roi_unit_stake'], -1)
        broken = deepcopy(state); broken['observations'][0]['payload']['shares']['home']['handle'] += 1
        with self.assertRaises(ValueError):
            validate_state(broken)
        with self.assertRaises(ValueError):
            settle(state, record, at=T)
        with self.assertRaises(ValueError):
            settle(state, record, confirmed=False)

    def test_bad_chronology_incomplete_market_and_12h_marker(self):
        for change in ('future_source', 'naive_time', 'incomplete_prices', 'bad_12h', 'future_news'):
            record = observation()
            if change == 'future_source':
                record['source']['observed_at'] = (T + timedelta(hours=1)).isoformat()
            elif change == 'naive_time':
                record['kickoff'] = '2026-01-02T12:00:00'
            elif change == 'incomplete_prices':
                record['odds'][0]['prices'].pop('away')
            elif change == 'bad_12h':
                record['odds'][0]['kind'] = '12h'
            else:
                record['news'][0]['source'] = source(T + timedelta(days=1))
            with self.subTest(change=change), self.assertRaises(ValueError):
                capture(empty_state(), [record])

    def test_fixture_identity_cannot_silently_change(self):
        state = capture(empty_state(), [observation()])
        changed = observation(); changed['away'] = 'C'
        with self.assertRaises(ValueError):
            capture(state, [changed])


class MarketBacktestTests(unittest.TestCase):
    def make_sample(self):
        state = empty_state()
        records = []
        for i in range(4):
            at = T + timedelta(days=i)
            record = observation(f'fixture-{i}', at=at)
            state = capture(state, [record], at)
            records.append(record)
        for i, record in enumerate(records):
            state = settle(state, record, at=T + timedelta(days=6, hours=i),
                           settlement={'home': 'win' if i%2 == 0 else 'loss',
                                       'away': 'loss' if i%2 == 0 else 'win'})
        return state

    def test_known_roi_and_paired_baseline(self):
        report = replay(self.make_sample())
        self.assertEqual(report['test_n'], 4)
        high, low = report['test']['high_handle'], report['test']['low_handle']
        self.assertAlmostEqual(high['roi_unit_stake'], -.1)
        self.assertAlmostEqual(low['roi_unit_stake'], .1)
        self.assertEqual(high['win_rate_decisive'], .5)
        self.assertEqual(high['paired_delta_roi_baseline'], 0)
        self.assertIsNotNone(high['roi_ci95_fixture_bootstrap'])
        self.assertEqual(report['test']['combined']['bets'], 4)
        self.assertEqual(report['test']['with_news']['bets'], 4)
        self.assertEqual(replay(self.make_sample()), report)
        self.assertTrue(report['controls'])
        self.assertTrue(report['warnings'])

    def test_deduplicates_publishers_at_same_original_book(self):
        record = observation(); copy = deepcopy(record)
        copy['source']['publisher'] = 'Another republisher'
        state = capture(empty_state(), [record, copy])
        state = settle(state, record)
        report = replay(state)
        self.assertEqual(report['test_n'], 1)
        self.assertEqual(report['test']['high_handle']['bets'], 1)

    def test_future_changes_cannot_change_frozen_signal(self):
        record = observation(); state = capture(empty_state(), [record]); state = settle(state, record)
        original = replay(state)
        later = observation(at=T + timedelta(hours=13), kickoff=datetime.fromisoformat(record['kickoff']))
        later['shares']['home']['handle'] = 0; later['shares']['away']['handle'] = 100
        state = capture(state, [later], T + timedelta(hours=13))
        updated = replay(state)
        self.assertEqual(original['rows'], updated['rows'])
        self.assertEqual(original['test'], updated['test'])

    def test_odds_source_and_news_must_be_known_by_cutoff(self):
        record = observation()
        # An odds point before cutoff whose source was only observed after cutoff is excluded.
        record['odds'][1]['source'] = source(T + timedelta(hours=13))
        state = capture(empty_state(), [record], T + timedelta(hours=13))
        self.assertEqual(replay(settle(state, record))['test_n'], 0)  # server commit after cutoff
        record = observation(); record['news'][0]['certainty'] = 'assumption'
        state = settle(capture(empty_state(), [record]), record)
        report = replay(state)
        self.assertEqual(report['test']['combined']['bets'], 1)
        self.assertEqual(report['test']['with_news']['bets'], 0)

    def test_stale_sources_and_changed_actual_kickoff_excluded(self):
        record = observation(); state = settle(capture(empty_state(), [record]), record)
        self.assertEqual(replay(state, max_age_hours=1)['test_n'], 0)
        state = settle(state, record, at=T + timedelta(days=2),
                       actual_kickoff=(T + timedelta(hours=20)).isoformat())
        self.assertEqual(replay(state)['test_n'], 0)

    def test_development_never_uses_results_not_known_at_test_start(self):
        state = self.make_sample()
        # First fixture starts before Jan 3 but all labels were only recorded Jan 7.
        report = replay(state, test_start='2026-01-03T00:00:00Z')
        self.assertEqual(report['development_n'], 0)
        self.assertEqual(report['test_n'], 3)

    def test_protocol_is_frozen_before_future_test_period(self):
        protocol = {'name': 'fixed rules', 'manifest': 'All specified fixtures, no discretionary exclusions',
                    'test_start': '2026-01-02T00:00:00Z', 'test_end': '2026-02-01T00:00:00Z',
                    'gap_threshold': 10, 'movement_threshold': 2, 'decision_hours': 12, 'max_age_hours': 24}
        state = self.make_sample()
        with patch('market_research.now', return_value=T):
            state = append_protocol(state, protocol)
        hashed = state['protocols'][0]['entry_hash']
        self.assertEqual(replay(state, protocol_hash=hashed)['mode'], 'preregistered_chronological')
        with self.assertRaises(ValueError):
            replay(state, protocol_hash=hashed, gap_threshold=0)
        with patch('market_research.now', return_value=T+timedelta(days=3)), self.assertRaises(ValueError):
            append_protocol(empty_state(), protocol)

    def test_push_void_and_half_settlement_are_explicit(self):
        record = observation(); state = capture(empty_state(), [record])
        state = settle(state, record, settlement={'home': 'half_win', 'away': 'half_loss'})
        report = replay(state)
        self.assertAlmostEqual(report['test']['high_handle']['roi_unit_stake'], .4)
        self.assertIsNone(report['test']['high_handle']['win_rate_decisive'])
        state = settle(state, record, at=T+timedelta(days=2), settlement={'home': 'void', 'away': 'void'})
        self.assertEqual(replay(state)['test']['high_handle']['bets'], 0)
        self.assertEqual(replay(state)['test']['high_handle']['voids'], 1)


class MarketCloudTests(unittest.TestCase):
    def setUp(self):
        self.cloud = MarketArchive('fixture-token', 'owner/private-repo')
        self.state = capture(empty_state(), [observation()])

    def responses(self, tail=None):
        result = [{'private': True}, {'encoding': 'base64', 'sha': 'expected-sha',
                  'content': base64.b64encode(canonical(self.state).encode()).decode()}]
        if tail is not None:
            result.append(tail)
        return result

    def test_separate_location_private_check_and_cas_write(self):
        with patch.object(self.cloud, '_request', side_effect=self.responses({'commit': {'sha': 'new'}})) as req:
            result = self.cloud.change(lambda state: state)
        self.assertEqual(result, self.state)
        put = req.call_args.args
        self.assertIn('/archive/market-research.json', put[1])
        self.assertEqual(put[2]['branch'], 'market-research')
        self.assertEqual(put[2]['sha'], 'expected-sha')
        self.assertNotIn('fixture-token', json.dumps(put[2]))
        original = GitHubArchive('fixture-token', 'owner/private-repo')
        self.assertEqual(original.branch, 'forecast-archive')
        self.assertIn('/archive/forecast-journal.json', original.endpoint)
        with patch.object(self.cloud, '_request', return_value={'private': False}) as req:
            with self.assertRaises(ValueError): self.cloud.load()
        self.assertEqual(req.call_count, 1)

    def test_old_history_cannot_be_replaced_or_shortened(self):
        for mutator in (lambda _: empty_state(), lambda s: {**s, 'observations': []}):
            with patch.object(self.cloud, '_request', side_effect=self.responses()) as req:
                with self.assertRaises(ValueError): self.cloud.change(mutator)
            self.assertEqual(req.call_count, 2)

    def test_conflict_or_missing_ack_never_reports_success(self):
        for response in (ValueError('conflict'), {}):
            with patch.object(self.cloud, '_request', side_effect=self.responses(response)) as req:
                with self.assertRaises(ValueError): self.cloud.change(lambda s: s)
            self.assertEqual(req.call_count, 3)

    def test_initialize_does_not_reset_existing_archive(self):
        with patch.object(self.cloud, '_private', return_value={'private': True}), patch.object(self.cloud, 'load', return_value=(self.state, 'sha')):
            self.assertEqual(self.cloud.initialize(), self.state)

    def test_corrupt_or_oversized_cloud_import_rejected(self):
        for body in (b'{}', b'x' * (2*1024*1024+1)):
            response = {'encoding': 'base64', 'sha': 'sha', 'content': base64.b64encode(body).decode()}
            with patch.object(self.cloud, '_request', side_effect=[{'private': True}, response]):
                with self.assertRaises(ValueError): self.cloud.load()


if __name__ == '__main__':
    unittest.main()
