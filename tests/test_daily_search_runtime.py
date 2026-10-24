"""Actual Streamlit widget transitions; fixture API only, temporary databases."""
from datetime import date
from io import BytesIO
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest
import odds_detective as data
import detective_ui as ui


class DailyRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=str(Path(self.tmp.name)/'odds.sqlite3')
        self.env=patch.dict(os.environ,{'ODDS_DB_PATH':self.path,'ODDS_API_KEY':'fixture-only-not-real'})
        self.env.start();self.addCleanup(self.env.stop)
        self.clock=patch.object(ui,'budapest_today',return_value=date(2026,10,24))
        self.clock.start();self.addCleanup(self.clock.stop)

    def app(self):
        app=AppTest.from_string('from detective_ui import run\nrun()').run()
        self.assertFalse(app.exception)
        return app

    def test_full_entrypoint_defaults_today_keeps_manual_day_and_never_auto_fetches(self):
        csv='Div,Date,HomeTeam,AwayTeam,FTHG,FTAG\n'+''.join(
            f'E0,{day:02d}/08/2026,A,B,2,1\n' for day in range(1,21))
        with patch('urllib.request.urlopen',side_effect=lambda *a,**k:BytesIO(csv.encode())),patch.object(ui,'list_football_leagues') as leagues,patch.object(ui,'list_football_events') as events,patch.object(ui,'collect_odds') as odds:
            app=AppTest.from_file(str(Path(__file__).parents[1]/'streamlit_app.py')).run()
            app.sidebar.radio[0].set_value('Oddsmozgás-nyomozó').run()
            self.assertFalse(app.exception)
            self.assertEqual(next(r for r in app.radio if r.label=='Nézet').value,'Napi mérkőzéskeresés')
            self.assertEqual(app.date_input(key='daily_match_day').value,date(2026,10,24))
            app.date_input(key='daily_match_day').set_value(date(2026,10,20)).run()
            app.run()
            self.assertEqual(app.date_input(key='daily_match_day').value,date(2026,10,20))
            for network in [leagues,events,odds]:network.assert_not_called()
        other=self.app()
        self.assertEqual(other.date_input(key='daily_match_day').value,date(2026,10,24))

    def test_daily_catalogue_clicks_create_correct_utc_match_and_preserve_history(self):
        league={'key':'soccer_fixture','title':'Test League'}
        event={'id':'event1','sport_key':'soccer_fixture','home_team':'Test Home','away_team':'Test Away','commence_time':'2026-10-23T22:30:00.000000+00:00'}
        with patch.object(ui,'list_football_leagues',return_value=[league]) as leagues,patch.object(ui,'list_football_events',return_value=[event]) as events,patch.object(ui,'collect_odds') as odds:
            app=self.app()
            store=data.Store(self.path);original=store.matches();store.close()
            app.button(key='load_odds_leagues').click().run()
            self.assertEqual(leagues.call_count,1)
            app.selectbox[0].set_value(league).run()
            app.button(key='load_odds_events').click().run()
            self.assertEqual(events.call_count,1)
            self.assertIn('2026-10-24 00:30 CEST',app.selectbox[1].options[0])
            app.selectbox[1].set_value(event).run()
            app.button(key='create_daily_investigation').click().run()
            self.assertFalse(app.exception)
            self.assertEqual(app.radio[0].value,'Mentett vizsgálatok / előzmények')
            store=data.Store(self.path);self.addCleanup(store.close)
            matches=store.matches();created=next(m for m in matches if m['home']=='Test Home')
            self.assertEqual(created['match_date'],'2026-10-23')
            self.assertEqual(app.selectbox(key='saved_investigation').value,created['id'])
            self.assertEqual(next(m for m in matches if m['id']==original[0]['id']),original[0])
            data.validate_event_binding(event,created)
            app.radio[0].set_value('Napi mérkőzéskeresés').run()
            app.date_input(key='daily_match_day').set_value(date(2026,10,25)).run()
            app.run()
            self.assertFalse(app.exception)
            self.assertEqual(leagues.call_count,1);self.assertEqual(events.call_count,1);odds.assert_not_called()

    def test_manual_creation_opens_new_investigation_in_actual_widgets(self):
        with patch.object(ui,'collect_odds') as odds,patch.object(ui,'list_football_events') as events:
            app=self.app()
            app.radio[0].set_value('Mentett vizsgálatok / előzmények').run()
            app.text_input[0].set_value('Manual Home')
            app.text_input[1].set_value('Manual Away')
            app.text_input[2].set_value('https://example.com/match')
            next(b for b in app.button if b.label=='Vizsgálat létrehozása').click().run()
            self.assertFalse(app.exception)
            store=data.Store(self.path);self.addCleanup(store.close)
            match=next(m for m in store.matches() if m['home']=='Manual Home')
            self.assertEqual(app.selectbox(key='saved_investigation').value,match['id'])
            odds.assert_not_called();events.assert_not_called()


if __name__=='__main__':unittest.main()
