"""Offline regression tests for Football Value AI's Poisson model."""
import importlib.util
import math
import pathlib
import sys
import types
import unittest
from datetime import date, timedelta
from unittest.mock import patch


def load_app():
    # Import pure model functions without requiring Streamlit installation.
    streamlit = types.ModuleType("streamlit")
    streamlit.cache_data = lambda **kwargs: lambda fn: fn
    previous = sys.modules.get("streamlit")
    sys.modules["streamlit"] = streamlit
    try:
        path = pathlib.Path(__file__).resolve().parents[1] / "streamlit_app.py"
        spec = importlib.util.spec_from_file_location("football_value_app", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        if previous is None:
            del sys.modules["streamlit"]
        else:
            sys.modules["streamlit"] = previous


class ModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = load_app()

    def test_poisson_mass_and_top_five(self):
        table = self.app.goltabla(1.5, 1.2)
        self.assertAlmostEqual(sum(p for _, _, p in table), 1, places=10)
        top = self.app.pontos_eredmenyek(1.5, 1.2)
        self.assertEqual(len(top), 5)
        self.assertEqual(top, sorted(top, key=lambda x: (-x[2], x[0], x[1])))
        self.assertTrue(all(0 < p < 1 for _, _, p in top))

    def test_invalid_lambdas(self):
        for value in (0, -1, float("nan"), float("inf"), 21):
            with self.assertRaises(ValueError):
                self.app.goltabla(value, 1.0)

    def test_backtest_score_metrics_and_no_same_day_leakage(self):
        teams = ["A", "B", "C", "D"]
        matches = []
        for day in range(100):
            d = date(2025, 8, 1) + timedelta(days=day)
            matches.append((teams[day % 4], teams[(day + 1) % 4], day % 3, (day + 1) % 3, d))
            matches.append((teams[(day + 2) % 4], teams[(day + 3) % 4], (day + 2) % 3, day % 2, d))
        scores, skipped, correct = self.app.visszateszt(matches)
        self.assertEqual(len(scores), len(correct))
        self.assertGreater(len(scores), 0)
        self.assertEqual(len(scores) + skipped, len(matches))
        self.assertTrue(all(r["top1"] <= r["top5"] for r in correct))
        self.assertTrue(all(0 <= r["top1_becsult"] <= r["top5_becsult"] <= 1 for r in correct))
        self.assertTrue(all(math.isfinite(a) and math.isfinite(b) for a, b in scores))

        # Retain the modified day and later records in both executions.
        # The estimator must receive only strictly earlier match dates.
        cutoff = matches[-4][4]
        changed = [(h, v, 9, 8, d) if d >= cutoff else (h, v, hg, vg, d)
                   for h, v, hg, vg, d in matches]
        predictions = []
        original = self.app.becsles
        def inspect(history, home, away):
            result = original(history, home, away)
            predictions.append((tuple(history), home, away, result))
            return result
        with patch.object(self.app, 'becsles', side_effect=inspect):
            _, _, before = self.app.visszateszt(matches)
        recorded = list(predictions)
        self.assertEqual(len(recorded), len(before))
        for row, (history, home, away, result) in zip(before, recorded):
            self.assertTrue(all(d.isoformat() < row['datum'] for *_, d in history))
            self.assertEqual((home, away), (row['hazai'], row['vendeg']))
        _, _, after = self.app.visszateszt(changed)
        eligible = [(a, b) for a, b in zip(before, after) if a['datum'] == cutoff.isoformat()]
        self.assertEqual(len(eligible), 2)
        for a, b in eligible:
            for field in ['top1_becsult', 'top5_becsult', 'elso_tipp', 'top5_tippek']:
                self.assertEqual(a[field], b[field])
        self.assertEqual(self.app.visszateszt(matches[:-2])[2], before[:-2])

    def test_empty_and_warmup_only(self):
        self.assertEqual(self.app.visszateszt([]), ([], 0, []))
        matches = [('A', 'B', 1, 1, date(2025, 8, 1))] * 20
        self.assertEqual(self.app.visszateszt(matches), ([], 20, []))

    def test_exact_score_hits_and_deterministic_ties(self):
        matches = [('A', 'B', 1, 1, date(2025, 8, 1) + timedelta(days=i)) for i in range(62)]
        _, skipped, rows = self.app.visszateszt(matches)
        self.assertEqual(skipped, 60)
        self.assertEqual(len(rows), 2)
        for row in rows:
            self.assertEqual(row['elso_tipp'], '0–0')
            self.assertEqual(row['top1'], 0)
            self.assertEqual(row['top5'], 1)
            self.assertEqual(row['valos_eredmeny'], '1–1')
            self.assertAlmostEqual(row['top1_becsult'], math.exp(-2))
            self.assertAlmostEqual(row['top5_becsult'], 4.5 * math.exp(-2))


if __name__ == "__main__":
    unittest.main()

