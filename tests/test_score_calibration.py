from dataclasses import replace
from datetime import date, timedelta
import math
import unittest
from score_calibration import Artifact, Example, fit, apply
from team_strength import outcome


class CalibrationTests(unittest.TestCase):
    def artifact(self, t=1.):
        return Artifact(t,60,date(2025,1,1),'fixture','fixture')

    def test_identity_matches_original_distribution_and_stable_nll(self):
        q=apply((1.5,1.2),self.artifact(),date(2025,1,2))
        old=outcome((1.5,1.2))
        for x,y in zip(q.one_x_two,old.one_x_two):self.assertAlmostEqual(x,y,places=12)
        for a,b in zip(q.top5,old.top5):
            self.assertEqual(a[:2],b[:2]);self.assertAlmostEqual(a[2],b[2],places=12)
        expected=1.5-2*math.log(1.5)+math.lgamma(3)+1.2-math.log(1.2)
        self.assertAlmostEqual(q.nll((2,1)),expected,places=12)

    def test_transformed_mass_rank_ties_and_recomputed_1x2(self):
        for lambdas in [(1.,1.),(.001,.001),(20.,20.),(1.5,1.2)]:
            for t in (.5,2.):
                q=apply(lambdas,self.artifact(t),date(2025,1,2))
                self.assertAlmostEqual(sum(map(math.exp,q.home_logp)),1,places=12)
                self.assertAlmostEqual(sum(map(math.exp,q.away_logp)),1,places=12)
                self.assertAlmostEqual(sum(q.one_x_two),1,places=12)
                self.assertEqual([x[:2] for x in q.top5],[x[:2] for x in outcome(lambdas).top5])
                self.assertTrue(math.isfinite(q.nll((100,100))))
        q=apply((1.,1.),self.artifact(2.),date(2025,1,2))
        pair=apply((1.5,1.2),self.artifact(2.),date(2025,1,2))
        ratio=math.exp(pair.home_logp[2]+pair.away_logp[1]-pair.home_logp[0]-pair.away_logp[0])
        self.assertAlmostEqual(ratio,math.sqrt(1.5**2*1.2/2),places=12)
        draw=sum(math.exp(h+a) for h,a in zip(q.home_logp,q.away_logp))
        self.assertAlmostEqual(q.one_x_two[1],draw,places=12)
        self.assertNotAlmostEqual(q.one_x_two[1],outcome((1.,1.)).one_x_two[1],places=5)

    def test_fit_excludes_current_future_before_hash_and_is_deterministic(self):
        cutoff=date(2025,4,1)
        history=[Example(date(2025,1,1)+timedelta(days=i),(1.5,1.2),(i%4,i%3)) for i in range(65)]
        future=[Example(cutoff+timedelta(days=i),(1.5,1.2),(9,9)) for i in range(2)]
        p=fit(history,cutoff)
        self.assertEqual(p,fit([*history,*future],cutoff))
        self.assertEqual(p,fit(list(reversed(history)),cutoff))
        self.assertEqual(p.training_matches,65)
        def loss(artifact):
            return sum(apply(e.lambdas,replace(artifact,trained_through=None),e.day).nll(e.label)
                       for e in history)/len(history)
        self.assertLessEqual(loss(p),loss(replace(p,temperature=1.))+1e-12)

    def test_selection_boundary_and_training_boundary_are_enforced(self):
        for artifact,day in [(self.artifact(),date(2025,1,1)),
                             (self.artifact(),date(2024,12,31)),
                             (replace(self.artifact(),selection_through=date(2025,2,1)),date(2025,2,1))]:
            with self.assertRaisesRegex(ValueError,'current or future'):
                apply((1.,1.),artifact,day)
        apply((1.,1.),replace(self.artifact(),selection_through=date(2025,2,1)),date(2025,2,2))

    def test_missing_history_and_invalid_inputs(self):
        p=fit([],date(2025,1,1))
        self.assertEqual(p.temperature,1.)
        self.assertEqual(p.reason,'insufficient_calibration_history')
        for t in (0,.49,2.01,math.nan,math.inf):
            with self.assertRaises(ValueError):apply((1.,1.),self.artifact(t),date(2025,1,2))
        with self.assertRaises(ValueError):Example(date(2025,1,1),(1.,1.),(101,0))
        with self.assertRaises(ValueError):apply((0.,1.),self.artifact(),date(2025,1,2))


if __name__=='__main__':unittest.main()
