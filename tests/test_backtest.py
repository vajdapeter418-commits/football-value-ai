"""Offline regression tests for Football Value AI's Poisson model."""
import importlib.util
import math
import pathlib
import sys
import types
import unittest
from datetime import date, timedelta


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

        # Modifying the last day's results must not change that day's forecasts.
        changed = list(matches)
        changed[-1] = (*changed[-1][:2], 9, 9, changed[-1][4])
        before, _, _ = self.app.visszateszt(matches[:-2])
        after, _, _ = self.app.visszateszt(changed[:-2])
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
