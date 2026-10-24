import math
import unittest
from dataclasses import replace, asdict
from datetime import date, timedelta
from unittest.mock import patch
from asof_features import snapshot, effective_n, age_weight
from team_strength import Config, predict, fit_core, outcome, poisson_ridge
from poisson_model import becsles, goltabla
from helpers import league, request


class ModelTests(unittest.TestCase):
    def test_hand_baseline_and_unchanged_main(self):
        from pathlib import Path
        import ast
        # Independent historical function definitions frozen in a fixture, not wrappers.
        namespace = {'math':math}
        tree=ast.parse((Path(__file__).parent/'fixtures'/'original_model.py').read_text())
        exec(compile(tree,'original_model','exec'),namespace)
        rows=[('A','B',2,1,date(2025,1,1)),('B','A',1,0,date(2025,1,2)),
              ('A','B',1,2,date(2025,1,3)),('C','D',0,1,date(2025,1,4))]
        old=namespace['becsles'](rows,'A','B')
        new=becsles(rows,'A','B')
        self.assertEqual(old,new)
        from asof_features import adapt_tuples
        p=predict(snapshot(adapt_tuples(rows),request()),'A','B')
        self.assertEqual(p.baseline,p.candidate)
        self.assertAlmostEqual(p.baseline.lambdas[0],((3+5*1)/7)**2/1)
        self.assertEqual(p.baseline.top5,tuple(namespace['pontos_eredmenyek'](*old[1:3])))
        for a,b in zip(old[0],p.baseline.one_x_two): self.assertAlmostEqual(a,b,places=12)

    def test_weight_and_effective_n(self):
        r=request()
        m=replace(league(1)[0],match_date=r.target_date-timedelta(days=90))
        self.assertEqual(age_weight(m,r),.5)
        self.assertAlmostEqual(effective_n([1,.5]),2.25/1.25)

    def test_joint_strength_direction_opponents_and_ridge(self):
        from asof_features import adapt_tuples
        rows=[]
        # Balanced venue schedule with strong A attack, weak D defence.
        teams='ABCD'
        for day in range(8):
            for h in teams:
                for a in teams:
                    if h!=a:
                        rows.append((h,a,1+2*(h=='A')+2*(a=='D'),1+2*(a=='A')+2*(h=='D'),date(2025,1,1)+timedelta(days=day)))
        snap=snapshot(adapt_tuples(rows),request())
        fit=fit_core(snap)
        self.assertTrue(fit.fit.converged)
        params={t:fit.fit.parameters[i*4:i*4+4] for i,t in enumerate(fit.teams)}
        self.assertGreater(params['A'][0],params['B'][0])
        self.assertGreater(params['D'][1],params['B'][1])
        self.assertGreater(fit.lambdas('A','D')[0],fit.lambdas('A','B')[0])
        strong_prior=fit_core(snap,Config(mode='core',ridge=1000))
        self.assertLess(sum(abs(x) for x in strong_prior.fit.parameters),sum(abs(x) for x in fit.fit.parameters))
        # Same A results, different opponent assignments changes its joint estimate.
        changed=[replace(m,away_id=('D' if m.away_id=='B' else 'B' if m.away_id=='D' else m.away_id))
                 if m.home_id=='A' else m for m in snap.matches]
        other=fit_core(snapshot(changed,request()))
        self.assertNotAlmostEqual(params['A'][0],other.fit.parameters[0],places=5)

    def test_solver_cap_fallback_and_guardrail(self):
        snap=snapshot(league(),request())
        p=predict(snap,'A','B',Config(mode='core'))
        self.assertIsNone(p.fallback_reason)
        self.assertTrue(p.solver[0])
        self.assertLessEqual(p.solver[2],1e-8)
        self.assertTrue(all(.75<=x<=1.25 for x in p.applied_ratios))
        f=predict(snap,'A','B',Config(mode='core',max_iterations=0))
        self.assertEqual(f.candidate,f.baseline)
        self.assertEqual(f.fallback_reason,'solver_not_converged')
        with patch('team_strength.fit_core',side_effect=OverflowError('fixture_solver_failure')):
            f=predict(snap,'A','B',Config(mode='core'))
        self.assertEqual(f.candidate,f.baseline)
        self.assertEqual(f.fallback_reason,'fixture_solver_failure')
        p=predict(snapshot(league(3),request()),'A','B',Config(mode='core'))
        self.assertEqual(p.fallback_reason,'insufficient_history_60_3_3')

    def test_probability_contract(self):
        for h,a in ((1,1),(1.5,1.2),(20,20),(.001,.001)):
            p=outcome((h,a))
            self.assertAlmostEqual(sum(v for _,_,v in goltabla(h,a)),1,places=10)
            self.assertAlmostEqual(sum(p.one_x_two),1,places=10)
            self.assertEqual(p.top5,tuple(sorted(p.top5,key=lambda x:(-x[2],x[0],x[1]))))
            self.assertLessEqual(sum(x[2] for x in p.top5),1)
        for v in (0,-1,math.nan,math.inf,21):
            with self.assertRaises(ValueError): goltabla(v,1)
        with self.assertRaises(ValueError): predict(snapshot(league(),request()),'A','A')
        with self.assertRaises(ValueError): predict(snapshot([],request()),'A','B')
        for value in (0,-1,math.nan,math.inf):
            with self.assertRaises(ValueError): Config(ridge=value)

    def test_newton_known_solution(self):
        f=poisson_ridge([(((0,1),),0,2,1)],1,5)
        self.assertTrue(f.converged)
        t=f.parameters[0]
        self.assertAlmostEqual(math.exp(t)-2+5*t,0,places=8)
