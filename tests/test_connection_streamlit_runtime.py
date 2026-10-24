"""Real Streamlit runtime smoke test, with a fixture key and no provider network."""
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


@unittest.skipUnless(importlib.util.find_spec('streamlit'),'Streamlit runtime not installed')
class StreamlitConnectionTests(unittest.TestCase):
    def test_click_cache_and_secret_redaction_in_actual_runtime(self):
        from streamlit.testing.v1 import AppTest
        import api_connection_ui as ui
        ui.cached_diagnostic.clear()
        self.addCleanup(ui.cached_diagnostic.clear)
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ,{'PREMATCH_ARCHIVE_DB':str(Path(directory)/'probe.sqlite3')}):
                with patch.object(ui,'capture_coverage',return_value={'coverage':{'injuries':True,
                     'fixtures':{'lineups':True,'statistics_fixtures':True}}}) as provider:
                    app=AppTest.from_string('from api_connection_ui import run\nrun()')
                    app.secrets['API_FOOTBALL_KEY']='fixture-only-not-real'
                    app.run()
                    self.assertFalse(app.exception);provider.assert_not_called()
                    app.button[0].click().run()
                    self.assertFalse(app.exception);self.assertEqual(provider.call_count,1)
                    self.assertEqual(len(app.success),1)
                    app.button[0].click().run()
                    self.assertFalse(app.exception);self.assertEqual(provider.call_count,1)
                    rendered=' '.join(str(x.value) for group in
                             [app.info,app.caption,app.success,app.warning,app.table] for x in group)
                    self.assertNotIn('fixture-only-not-real',rendered)


if __name__=='__main__':unittest.main()
