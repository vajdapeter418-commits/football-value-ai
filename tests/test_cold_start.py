"""Sparse-team and season reset checks, with frozen model parameters."""
from dataclasses import replace
from datetime import date, timedelta
import unittest

from asof_features import adapt_tuples, snapshot
from team_strength import Config, predict
from helpers import league, request


class ColdStartTests(unittest.TestCase):
    def test_one_or_two_venue_matches_fall_back_without_fake_strength(self):
        for count in (1, 2):
            with self.subTest(venue_matches=count):
                rows = list(league(40))
                for i in range(count):
                    rows.extend(adapt_tuples([
                        ('NewHome', 'C', 2, 1, date(2025, 2, 15) + timedelta(days=i)),
                        ('D', 'NewAway', 1, 1, date(2025, 2, 15) + timedelta(days=i))]))
                req = request(home='NewHome', away='NewAway')
                p = predict(snapshot(rows, req), req.home, req.away, Config(mode='core'))
                self.assertEqual(p.raw_counts[1:], (count, count))
                self.assertEqual(p.candidate, p.baseline)
                self.assertEqual(p.fallback_reason, 'insufficient_history_60_3_3')
                self.assertFalse(p.active_signals)

    def test_three_venue_matches_allow_shrunk_bounded_prediction(self):
        rows = list(league(40))
        for i in range(3):
            rows.extend(adapt_tuples([
                ('NewHome', 'C', 2, 1, date(2025, 2, 15) + timedelta(days=i)),
                ('D', 'NewAway', 1, 1, date(2025, 2, 15) + timedelta(days=i))]))
        req = request(home='NewHome', away='NewAway')
        p = predict(snapshot(rows, req), req.home, req.away, Config(mode='core'))
        self.assertIsNone(p.fallback_reason)
        self.assertTrue(p.solver[0])
        self.assertEqual(p.raw_counts[1:], (3, 3))
        self.assertTrue(all(.75 <= x <= 1.25 for x in p.applied_ratios))

    def test_no_venue_history_is_explicitly_unavailable(self):
        req = request(home='UnknownHome', away='UnknownAway')
        with self.assertRaises(ValueError):
            predict(snapshot(league(40), req), req.home, req.away, Config(mode='core'))

    def test_previous_season_is_not_silently_carried_forward(self):
        req = replace(request(), season='new-season')
        self.assertFalse(snapshot(league(), req).matches)
        with self.assertRaisesRegex(ValueError, 'empty_snapshot'):
            predict(snapshot(league(), req), req.home, req.away, Config(mode='core'))

    def test_same_day_and_future_high_scores_cannot_change_sparse_prediction(self):
        req = request(home='A', away='B')
        old = league(3)
        injected = adapt_tuples([
            ('A', 'B', 19, 18, req.target_date),
            ('A', 'B', 17, 16, req.target_date + timedelta(days=1))])
        before = snapshot(old, req)
        after = snapshot((*old, *injected), req)
        self.assertEqual(before, after)
        self.assertEqual(predict(before, 'A', 'B', Config(mode='core')),
                         predict(after, 'A', 'B', Config(mode='core')))


if __name__ == '__main__':
    unittest.main()
