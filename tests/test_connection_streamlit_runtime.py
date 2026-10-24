"""Real Streamlit runtime smoke test, with a fixture key and no provider network."""
import importlib.util
from io import BytesIO
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


@unittest.skipUnless(importlib.util.find_spec('streamlit'),'Streamlit runtime not installed')
class StreamlitConnectionTests(unittest.TestCase):
    def test_main_entrypoint_routes_to_probe_without_other_downloads(self):
        from streamlit.testing.v1 import AppTest
        import api_connection_ui as ui
        ui.cached_diagnostic.clear()
        self.addCleanup(ui.cached_diagnostic.clear)
        data='Div,Date,HomeTeam,AwayTeam,FTHG,FTAG\n'+''.join(
             f'E0,{day:02d}/08/2026,A,B,2,1\n' for day in range(1,21))
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ,{'PREMATCH_ARCHIVE_DB':str(Path(directory)/'probe.sqlite3')}):
                with patch('urllib.request.urlopen',side_effect=lambda *a,**k:BytesIO(data.encode())) as public:
                    with patch.object(ui,'capture_coverage',return_value={'coverage':{'injuries':True}}) as provider:
                        app=AppTest.from_file(str(Path(__file__).parents[1]/'streamlit_app.py'))
                        app.secrets['API_FOOTBALL_KEY']='fixture-only-not-real'
                        app.run();self.assertFalse(app.exception)
                        original_calls=public.call_count
                        app.sidebar.radio[0].set_value('API-kapcsolat ellenőrzése').run()
                        self.assertFalse(app.exception);provider.assert_not_called()
                        self.assertEqual(public.call_count,original_calls)
                        app.button(key='api_check_button').click().run()
                        self.assertFalse(app.exception);self.assertEqual(provider.call_count,1)
                        self.assertEqual(len(app.success),1)
                        app.button(key='api_check_button').click().run()
                        self.assertEqual(provider.call_count,1)
                        self.assertEqual(public.call_count,original_calls)

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
