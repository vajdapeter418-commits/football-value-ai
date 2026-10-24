import ast
import json
import math
from pathlib import Path
import unittest
from dataclasses import replace, asdict
from datetime import date
from correct_score_backtest import backtest, nll, wilson, paired_bootstrap
from team_strength import Config, predict
from asof_features import snapshot
from helpers import league, request


class BacktestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.matches=league(35)
        cls.report=backtest(cls.matches)

    def test_paired_denominators_metrics_and_splits(self):
        r=self.report
        self.assertEqual(r['evaluated']+sum(r['skipped'].values()),r['total'])
        self.assertGreater(r['evaluated'],0)
        self.assertEqual(r['evidence'],'insufficient')
        self.assertFalse(r['activation_recommended'])
        self.assertEqual(r['default_model'],'baseline')
        for row in r['rows']:
            ids=set(row['forecasts'])
            self.assertEqual(ids,set(row['metrics']))
            for score in row['metrics'].values():
                self.assertLessEqual(score['top1'],score['top5'])
                self.assertLessEqual(score['estimated_top1'],score['estimated_top5'])
                self.assertLessEqual(score['estimated_top5'],1)
                self.assertTrue(math.isfinite(score['nll']))
            # No evaluator label in the serialized feature/forecast object.
            self.assertNotIn('label',json.dumps(row['forecasts']))
        self.assertEqual(r['split_dates']['development'],['2025-01-01','2025-01-21'])
        self.assertEqual(r['split_dates']['validation'],['2025-01-22','2025-01-28'])
        self.assertEqual(r['split_dates']['test'],['2025-01-29','2025-02-04'])

    def test_own_day_forecasts_compared_without_dropping_the_day(self):
        day=self.matches[-1].match_date
        changed=[replace(m,home_goals=9,away_goals=8) if m.match_date==day else m for m in self.matches]
        other=backtest(changed)
        before=[r for r in self.report['rows'] if r['date']==str(day)]
        after=[r for r in other['rows'] if r['date']==str(day)]
        self.assertEqual(len(before),2);self.assertEqual(len(after),2)
        self.assertEqual([r['forecasts'] for r in before],[r['forecasts'] for r in after])
        self.assertNotEqual([r['label'] for r in before],[r['label'] for r in after])
        self.assertNotEqual([r['metrics'] for r in before],[r['metrics'] for r in after])

    def test_permutation_and_future_add_remove(self):
        other=backtest(tuple(reversed(self.matches)))
        self.assertEqual(other['rows'],self.report['rows'])
        day=self.matches[-1].match_date
        future=tuple(replace(m,match_date=m.match_date.replace(year=2026)) for m in league(2))
        # use different IDs for distinct fixtures
        future=tuple(replace(m,match_id='future-'+m.match_id) for m in future)
        later=backtest((*self.matches,*future))
        self.assertEqual([r['forecasts'] for r in later['rows'] if r['date']<=str(day)],
                         [r['forecasts'] for r in self.report['rows']])

    def test_ui_and_backtest_share_entrypoint_and_snapshot(self):
        row=self.report['rows'][-1]
        target=next(m for m in self.matches if m.match_id==row['match_id'])
        req=request(target.match_date,home=target.home_id,away=target.away_id)
        p=predict(snapshot(self.matches,req),req.home,req.away,Config(mode='core'))
        self.assertEqual(asdict(p),row['forecasts']['core'])
        tree=ast.parse((Path(__file__).parents[1]/'streamlit_app.py').read_text())
        self.assertTrue(any(isinstance(n,ast.Call) and isinstance(n.func,ast.Name)
                            and n.func.id=='predict' for n in ast.walk(tree)))

    def test_wilson_bootstrap_and_stable_logpmf(self):
        lo,hi=wilson(0,10);self.assertAlmostEqual(lo,0);self.assertGreater(hi,0)
        lo,hi=wilson(10,10);self.assertAlmostEqual(hi,1);self.assertLess(lo,1)
        self.assertTrue(math.isfinite(nll((.0001,20),(10000,20000))))
        self.assertEqual(paired_bootstrap(self.report['rows']),paired_bootstrap(self.report['rows']))
