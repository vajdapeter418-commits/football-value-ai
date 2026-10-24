from copy import deepcopy
from datetime import datetime, timedelta, timezone, date
import os
import tempfile
from pathlib import Path
import detective_ui as detective
import unittest
from unittest.mock import patch
from streamlit.testing.v1 import AppTest
from streamlit.proto.TextInput_pb2 import TextInput
from forecast_journal import Journal
from forecast_cloud import empty_state, validate_state
import forecast_journal_ui as ui


class FakeCloud:
    def __init__(self,state=None):self.state=state or empty_state();self.loads=0;self.writes=0
    def load(self):self.loads+=1;return deepcopy(self.state),'fixture-sha'
    def change(self,mutator):
        updated=mutator(deepcopy(self.state));validate_state(updated)
        self.state=deepcopy(updated);self.writes+=1;return updated


class JournalRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.clock=datetime(2026,10,24,12,tzinfo=timezone.utc)
        self.raw=('Div,Date,HomeTeam,AwayTeam,FTHG,FTAG\n'+''.join(
            f"E0,{date(2026,8,1)+timedelta(days=i):%d/%m/%Y},{'A,B,2,1' if i%2==0 else 'C,D,1,2'}\n"
            for i in range(80))).encode()
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        env=patch.dict(os.environ,{'ODDS_DB_PATH':str(Path(self.temp.name)/'odds.sqlite3')})
        env.start();self.addCleanup(env.stop)
        self.cloud=FakeCloud()
        p=patch.object(ui,'cloud',return_value=self.cloud);p.start();self.addCleanup(p.stop)

    def app(self,code='from forecast_journal_ui import run\nrun()',secrets=True):
        app=AppTest.from_string(code)
        if secrets:
            app.secrets.update({'FORECAST_ARCHIVE_TOKEN':'fixture-secret-token',
                'FORECAST_JOURNAL_PASSWORD':'fixture-password','FORECAST_ARCHIVE_REPOSITORY':'owner/private-repo','ODDS_API_KEY':'fixture-odds-key'})
        app.run();self.assertFalse(app.exception)
        return app

    def unlock(self,app):
        next(x for x in app.text_input if x.label=='Napló jelszava').set_value('fixture-password').run()
        self.assertFalse(app.exception)

    def test_missing_config_and_wrong_password_never_access_cloud(self):
        with patch.dict(os.environ,{'FORECAST_ARCHIVE_TOKEN':'','FORECAST_JOURNAL_PASSWORD':'','FORECAST_ARCHIVE_REPOSITORY':''}):
            app=self.app(secrets=False)
        self.assertEqual(self.cloud.loads,0);self.assertEqual(self.cloud.writes,0)
        app=self.app();app.text_input[0].set_value('wrong').run()
        self.assertEqual(self.cloud.loads,0)
        app.secrets['FORECAST_JOURNAL_PASSWORD']='árvíz-fixture'
        app.text_input[0].set_value('árvíz-fixture').run()
        self.assertFalse(app.exception);self.assertEqual(self.cloud.loads,1)

    def test_daily_selected_match_save_then_new_session_restores_cloud(self):
        league={'key':'soccer_epl','title':'EPL'}
        event={'id':'fixture1','sport_key':'soccer_epl','home_team':'A','away_team':'B',
               'commence_time':'2026-10-25T12:00:00Z'}
        with patch.object(ui,'download_csv',return_value=self.raw) as provider,patch('forecast_journal.now',return_value=self.clock),patch.object(detective,'list_football_leagues',return_value=[league]),patch.object(detective,'list_football_events',return_value=[event]):
            app=self.app('from detective_ui import run\nrun()')
            app.date_input(key='daily_match_day').set_value(date(2026,10,25)).run()
            app.button(key='load_odds_leagues').click().run()
            app.selectbox[0].set_value(league).run()
            app.button(key='load_odds_events').click().run()
            app.selectbox[1].set_value(event).run()
            self.unlock(app);provider.assert_not_called()
            app.button(key='prepare_frozen_forecast').click().run()
            self.assertEqual(provider.call_count,1)
            app.checkbox[0].set_value(True)
            next(x for x in app.button if x.label=='Pontos tipp végleges mentése').click().run()
            self.assertFalse(app.exception);self.assertEqual(self.cloud.writes,1)
            self.assertTrue(any('felhőarchívumba került' in x.value for x in app.success))
        fresh=self.app();self.unlock(fresh)
        self.assertEqual(next(x.value for x in fresh.metric if x.label=='Mentett tippek'),'1')
        self.assertEqual(self.cloud.state['journal']['count'],1)
        rendered=' '.join(str(x.value) for group in [fresh.caption,fresh.info,fresh.success,fresh.error] for x in group)
        self.assertNotIn('fixture-secret-token',rendered)
        self.assertEqual(fresh.text_input[0].proto.type,TextInput.PASSWORD)

    def test_completed_result_is_written_and_metrics_refresh(self):
        journal=Journal(':memory:')
        try:
            with patch('forecast_journal.now',return_value=self.clock):
                journal.capture(self.raw,fixture_id='fixture1',home='A',away='B',season='2026/27',
                    kickoff='2026-10-25T12:00:00Z',source_url='https://www.football-data.co.uk/mmz4281/2627/E0.csv')
            self.cloud.state['journal']=journal.export()
        finally:journal.close()
        with patch('forecast_cloud.now',return_value=self.clock+timedelta(days=2)):
            app=self.app();self.unlock(app)
            next(x for x in app.number_input if x.label=='Végeredmény: hazai gól').set_value(1)
            next(x for x in app.number_input if x.label=='Végeredmény: vendég gól').set_value(1)
            app.checkbox[0].set_value(True)
            next(x for x in app.button if x.label=='Végeredmény rögzítése').click().run()
        self.assertFalse(app.exception)
        self.assertEqual(next(x.value for x in app.metric if x.label=='Értékelt mérkőzések'),'1')
        self.assertEqual(self.cloud.writes,1)
        self.assertEqual(len(self.cloud.state['results']),1)

    def test_main_entrypoint_routes_to_journal_without_cloud_before_login(self):
        from pathlib import Path
        from io import BytesIO
        with patch('urllib.request.urlopen',side_effect=lambda *a,**k:BytesIO(self.raw)):
            app=AppTest.from_file(str(Path(__file__).parents[1]/'streamlit_app.py')).run()
            app.sidebar.radio[0].set_value('Tippek naplója').run()
            self.assertFalse(app.exception)
            self.assertEqual(self.cloud.loads,0)
            self.assertTrue(any('nincs beállítva' in x.value for x in app.info))

    def test_failed_cloud_write_does_not_show_success(self):
        code="from forecast_journal_ui import capture_event\ncapture_event({'id':'fixture1','home_team':'A','away_team':'B','commence_time':'2026-10-25T12:00:00Z'})"
        with patch.object(ui,'download_csv',return_value=self.raw),patch.object(self.cloud,'change',side_effect=ValueError('conflict')):
            app=self.app(code);self.unlock(app);app.button(key='prepare_frozen_forecast').click().run()
            app.checkbox[0].set_value(True)
            next(x for x in app.button if x.label=='Pontos tipp végleges mentése').click().run()
        self.assertFalse(app.exception);self.assertFalse(app.success)
        self.assertTrue(app.error)


if __name__=='__main__':unittest.main()
