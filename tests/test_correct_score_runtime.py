"""Correct-score backtest in the real Streamlit runtime, offline CSV fixtures."""
from datetime import date, timedelta
from io import BytesIO
from pathlib import Path
import unittest
from unittest.mock import patch

import streamlit as st
from streamlit.testing.v1 import AppTest


class CorrectScoreRuntimeTests(unittest.TestCase):
    def run_backtest(self, count):
        st.cache_data.clear()
        self.addCleanup(st.cache_data.clear)
        csv = 'Div,Date,HomeTeam,AwayTeam,FTHG,FTAG\n' + ''.join(
            f'E0,{date(2025,8,1)+timedelta(days=i):%d/%m/%Y},A,B,1,1\n'
            for i in range(count))
        with patch('urllib.request.urlopen', side_effect=lambda *a, **k: BytesIO(csv.encode())):
            app = AppTest.from_file(str(Path(__file__).parents[1] / 'streamlit_app.py')).run()
            self.assertFalse(app.exception)
            next(b for b in app.button if b.label == 'Visszateszt indítása').click().run()
            self.assertFalse(app.exception)
            return app

    def test_backtest_renders_correct_score_metrics(self):
        app = self.run_backtest(80)
        metrics = {m.label: m.value for m in app.metric}
        self.assertEqual(metrics['Tesztelt mérkőzések'], '20')
        self.assertEqual(metrics['Első tipp találati aránya'], '0.0%')
        self.assertEqual(metrics['Top 5 találati aránya'], '100.0%')
        self.assertTrue(any('akkori szolgáltatói elérhetőségét' in c.value for c in app.caption))

    def test_warmup_only_does_not_render_invalid_percentages(self):
        app = self.run_backtest(20)
        metrics = {m.label: m.value for m in app.metric}
        self.assertEqual(metrics['Tesztelt mérkőzések'], '0')
        self.assertNotIn('Első tipp találati aránya', metrics)
        self.assertTrue(any('Még nincs elég adat' in x.value for x in app.info))


if __name__ == '__main__':
    unittest.main()
