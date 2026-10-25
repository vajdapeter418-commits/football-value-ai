"""Real Streamlit UI tests in CI; no deployed app, secrets or network required."""
from datetime import datetime, timedelta, timezone
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from technical_test import APP, HOST, TestStore

HAS_STREAMLIT = importlib.util.find_spec('streamlit') is not None
if HAS_STREAMLIT:
    from streamlit.testing.v1 import AppTest
    import technical_test_ui as ui


@unittest.skipUnless(HAS_STREAMLIT, 'Streamlit unavailable; real runtime tests run in GitHub CI')
class TechnicalRuntimeTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name) / APP
        for mock in (patch.dict(os.environ, {'FVA_TECH_TEST_ENABLED': '1',
                                            'FVA_TECH_TEST_ROOT': str(self.root)}),
                     patch.object(ui, '_url', return_value='https://' + HOST),
                     patch.object(ui, '_authorized', return_value=True),
                     patch('forecast_cloud.GitHubArchive._request', side_effect=AssertionError('No cloud access'))):
            mock.start()
            self.addCleanup(mock.stop)

    def app(self):
        app = AppTest.from_string('from technical_test_ui import run\nrun()', default_timeout=15)
        app.run()
        self.assertFalse(app.exception)
        return app

    def test_unauthorized_visitors_cannot_read_or_write(self):
        with patch.object(ui, '_authorized', return_value=False), patch.object(ui, 'TestStore') as store:
            app = self.app()
            store.assert_not_called()
        self.assertTrue(app.error)
        self.assertEqual([b.label for b in app.button], ['TESZT bejelentkezés'])
        self.assertFalse(app.dataframe)
        self.assertFalse(self.root.exists())

    def test_manual_save_and_new_ui_session_readback(self):
        app = self.app()
        next(x for x in app.number_input if x.label == 'TESZT odds home').set_value(2.75)
        next(b for b in app.button if b.label == 'TESZT mérkőzés és odds mentése').click().run()
        self.assertFalse(app.exception)
        self.assertTrue(app.success)
        restored = self.app()
        self.assertEqual(len(restored.dataframe[0].value), 1)
        store = TestStore(self.root, url='https://' + HOST, enabled='1')
        self.assertEqual(store.load()['observations'][0]['payload']['odds'][0]['prices']['home'], 2.75)

    def test_wrong_host_blocks_store_and_original_navigation(self):
        with patch.object(ui, '_url', return_value='https://production.streamlit.app'):
            app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'technical_test_app.py'))
            app.run()
        self.assertFalse(app.exception)
        self.assertTrue(app.error)
        self.assertFalse(app.radio)
        self.assertFalse(app.button)
        self.assertFalse(self.root.exists())

    def test_missing_storage_has_no_fallback(self):
        with patch.dict(os.environ, {'FVA_TECH_TEST_ROOT': ''}):
            app = self.app()
        self.assertTrue(app.error)
        self.assertFalse(app.button)
        self.assertFalse(self.root.exists())

    def test_disabled_or_missing_url_blocks_all_forms(self):
        with patch.dict(os.environ, {'FVA_TECH_TEST_ENABLED': ''}):
            app = self.app()
        self.assertTrue(app.error)
        self.assertFalse(app.button)
        with patch.object(ui, '_url', return_value=''):
            app = self.app()
        self.assertTrue(app.error)
        self.assertFalse(self.root.exists())

    def test_storage_error_never_renders_exception_or_configuration(self):
        with patch.object(ui, 'TestStore', side_effect=RuntimeError('DO_NOT_DISCLOSE_SENTINEL')):
            app = self.app()
        self.assertTrue(app.error)
        rendered = ' '.join(str(x.value) for group in (app.error, app.caption, app.markdown) for x in group)
        self.assertNotIn('DO_NOT_DISCLOSE_SENTINEL', rendered)
        self.assertNotIn(str(self.root), rendered)

    def test_result_and_actual_backtest_ui(self):
        store = TestStore(self.root, url='https://' + HOST, enabled='1')
        clock = datetime.now(timezone.utc)
        captured = clock - timedelta(days=2)
        with patch('market_research.now', return_value=captured):
            store.save_match(fixture='finished', home='A', away='B',
                kickoff=(captured + timedelta(days=1)).isoformat(), observed_at=captured.isoformat(),
                prices={'home': 2.3, 'draw': 3.2, 'away': 3.0})
        app = self.app()
        ended = next(x for x in app.text_input if x.label == 'TESZT befejezés UTC')
        ended.set_value((clock - timedelta(hours=20)).isoformat())
        next(b for b in app.button if b.label == 'TESZT eredmény mentése').click().run()
        self.assertFalse(app.exception)
        self.assertEqual(len(store.load()['results']), 1)
        next(b for b in app.button if b.label == 'TESZT visszateszt futtatása').click().run()
        self.assertFalse(app.exception)
        self.assertEqual(len(app.dataframe[-1].value), 1)


if __name__ == '__main__':
    unittest.main()
