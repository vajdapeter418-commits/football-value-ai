"""Regression coverage for revocations and evaluator/archive separation."""
from dataclasses import replace, asdict
from datetime import datetime, timedelta, timezone
import unittest
from unittest.mock import patch

from asof_features import STRICT, snapshot
from correct_score_backtest import backtest
from helpers import evidence, league, request
from team_strength import Config, predict


def archive(days=33):
    rows = []
    for m in league(days):
        kickoff = datetime.combine(m.match_date, datetime.min.time(), timezone.utc)
        finished = kickoff + timedelta(hours=2)
        rows.append(replace(m, kickoff_utc=kickoff, completed_at=finished,
                            evidence=evidence(finished, record=m.match_id)))
    return tuple(rows)


class StrictRegressions(unittest.TestCase):
    def test_latest_available_revocation_never_resurrects_old_version(self):
        m = archive(1)[0]
        req = request(policy=STRICT)
        known = req.prediction_cutoff - timedelta(days=1)
        changes = [dict(completed=False, home_goals=None, away_goals=None, completed_at=None),
                   dict(completed_at=req.prediction_cutoff),
                   dict(kickoff_utc=None), dict(regulation=False)]
        for fields in changes:
            with self.subTest(fields=fields):
                revoked = replace(m, evidence=evidence(known, version=2), **fields)
                self.assertFalse(snapshot((m, revoked), req).matches)
                future = replace(revoked, evidence=evidence(req.prediction_cutoff, version=2))
                self.assertEqual(snapshot((m, future), req), snapshot((m,), req))
        revoked = replace(m, evidence=replace(evidence(known, version=2), verification='revoked'))
        self.assertFalse(snapshot((m, revoked), req).matches)

    def test_strict_labels_and_training_use_cutoff_archive(self):
        history = archive()
        labels = tuple(replace(m, home_goals=8, away_goals=7, evidence=None) for m in history)
        old = history[0]
        late = replace(old, home_goals=9, evidence=evidence(
            history[-1].kickoff_utc + timedelta(days=1), version=2))
        seen = []
        def train(examples, cutoff, config):
            seen.append(tuple(examples))
            return None
        with patch('correct_score_backtest.train_extra', side_effect=train):
            report = backtest(labels, policy=STRICT, historical_matches=(*history, late))
        self.assertTrue(report['rows'])
        self.assertTrue(any(seen))
        by_id = {m.match_id:m for m in labels}
        for row in report['rows']:
            target = by_id[row['match_id']]
            req = request(target.match_date, STRICT, target.home_id, target.away_id)
            req = replace(req, kickoff_utc=target.kickoff_utc)
            expected = predict(snapshot(history, req), req.home, req.away, Config(mode='core'))
            self.assertEqual(row['forecasts']['core'], asdict(expected))
            self.assertEqual(row['label'], (8, 7))
        self.assertTrue(all(ex.label != (8, 7) for batch in seen for ex in batch))
        for batch in seen:
            for ex in batch:
                candidates = {(m.home_goals,m.away_goals) for m in history
                              if m.kickoff_utc == ex.cutoff}
                self.assertIn(ex.label, candidates)
        altered = tuple(replace(m, home_goals=6) for m in labels)
        other = backtest(altered, policy=STRICT, historical_matches=history)
        self.assertEqual([r['forecasts'] for r in report['rows']],
                         [r['forecasts'] for r in other['rows']])
        with self.assertRaisesRegex(ValueError, 'historical_matches'):
            backtest(labels, policy=STRICT)
