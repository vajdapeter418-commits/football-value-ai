"""Independent hand checks for the read-only forecast diagnostic."""
import math
import unittest
from research.diagnose_baseline import enrich, calibration, residual_intervals


class BaselineDiagnosticTests(unittest.TestCase):
    def row(self):
        return {'actual_home':'1','actual_away':'1','lambda_home':'1','lambda_away':'1',
                'top1_home':'0','top1_away':'0','top1_probability':str(math.exp(-2)),
                'top1_hit':'0','season':'fixture','date':'2025-01-01','split':'test'}

    def test_hand_poisson_scores_and_goal_residuals(self):
        r=enrich(self.row())
        self.assertEqual(r['total_bias'],0)
        self.assertEqual(r['draw_actual'],1)
        self.assertEqual(r['1-1_actual'],1)
        self.assertEqual(r['0-0_actual'],0)
        for score in ['0-0','1-1','1-0','0-1']:
            self.assertAlmostEqual(r[score+'_expected'],math.exp(-2))
        self.assertAlmostEqual(r['2-2_expected'],math.exp(-2)/4)
        expected_draw=math.exp(-2)*sum(1/math.factorial(k)**2 for k in range(30))
        self.assertAlmostEqual(r['draw_expected'],expected_draw)

    def test_bins_include_boundary_once_and_use_predictions_only(self):
        rows=[{'season':'s','date':'2025-01-01','top1_expected':p,
               'top1_actual':hit,'top1_bias':hit-p} for p,hit in [(.1,0),(.15,1),(.2,0)]]
        bins=calibration(rows,'top1',(0,.1,.15,.2,1.0000001))
        self.assertEqual([r['n'] for r in bins],[0,1,1,1])
        self.assertEqual(bins[2]['hits'],1)
        self.assertEqual(bins[2]['expected'],.15)

    def test_constant_cluster_residual_has_constant_interval(self):
        rows=[{'season':'s','date':day,'error_bias':.25} for day in ['2025-01-01','2025-01-02']]
        self.assertEqual(residual_intervals(rows,['error_bias']),{'error_bias':[.25,.25]})

    def test_invalid_saved_forecast_is_rejected(self):
        for updates in [{'lambda_home':'nan'}, {'top1_hit':'1'}, {'top1_probability':'.9'}]:
            with self.subTest(updates=updates),self.assertRaises(ValueError):
                enrich({**self.row(),**updates})


if __name__=='__main__':unittest.main()
