"""Real Streamlit runtime checks with a fake private cloud, never production writes."""
from copy import deepcopy
from datetime import timedelta
import os
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest
import market_ui as ui
from market_research import empty_state, validate_state
from test_market_research import T, capture, observation


class FakeCloud:
    def __init__(self, state=None):
        self.state = deepcopy(state or empty_state())
        self.loads = 0
        self.writes = 0

    def load(self):
        self.loads += 1
        return deepcopy(self.state), 'fixture-sha'

    def change(self, mutator):
        state = validate_state(mutator(deepcopy(self.state)))
        self.state = deepcopy(state)
        self.writes += 1
        return state


class MarketRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.cloud = FakeCloud(capture(empty_state(), [observation()]))
        mock = patch.object(ui, 'cloud', return_value=self.cloud)
        mock.start(); self.addCleanup(mock.stop)

    def app(self, secrets=True, code='from market_ui import run\nrun()'):
        app = AppTest.from_string(code, default_timeout=15)
        if secrets:
            app.secrets.update({'FORECAST_ARCHIVE_TOKEN': 'fixture-secret-token',
                                'FORECAST_JOURNAL_PASSWORD': 'fixture-password',
                                'FORECAST_ARCHIVE_REPOSITORY': 'owner/private-repo'})
        app.run()
        self.assertFalse(app.exception)
        return app

    def unlock(self, app):
        app.text_input(key='forecast_password').set_value('fixture-password')
        next(b for b in app.button if b.label == 'Belépés').click().run()
        self.assertFalse(app.exception)

    def set_text(self, app, label, value):
        next(x for x in app.text_input if x.label == label).set_value(value)

    def test_authentication_precedes_all_reads_and_writes(self):
        with patch.dict(os.environ, {'FORECAST_ARCHIVE_TOKEN': '', 'FORECAST_JOURNAL_PASSWORD': '',
                                     'FORECAST_ARCHIVE_REPOSITORY': ''}):
            self.app(secrets=False)
        app = self.app()
        self.assertEqual(self.cloud.loads, 0)
        app.text_input(key='forecast_password').set_value('wrong')
        next(b for b in app.button if b.label == 'Belépés').click().run()
        self.assertTrue(app.error)
        self.assertEqual(self.cloud.loads, 0)
        self.assertEqual(self.cloud.writes, 0)
        self.unlock(app)
        self.assertEqual(self.cloud.loads, 1)
        rendered = str(app)
        self.assertNotIn('fixture-secret-token', rendered)

    def test_verified_only_tables_and_tickets_only_warning(self):
        record = observation()
        for s in record['shares'].values():
            s.update(handle=None, handle_origin='unavailable')
        self.cloud.state = capture(empty_state(), [record])
        app = self.app(); self.unlock(app)
        self.assertTrue(any('Csak tickets' in x.value for x in app.warning))
        self.assertTrue(app.dataframe)
        app.button(key='refresh_market').click().run()
        self.assertFalse(app.exception)
        self.assertEqual(self.cloud.loads, 2)

    def test_manual_form_persists_then_new_session_restores(self):
        app = self.app(); self.unlock(app)
        next(x for x in app.radio if x.label == 'Piaci nézet').set_value('Kézi bevitel').run()
        self.set_text(app, 'Kimenetelek vesszővel elválasztva', 'home,away')
        app.run()
        values = {'Fixture azonosító': 'fixture-new', 'Hazai csapat': 'C', 'Vendégcsapat': 'D',
                  'Piac': 'moneyline', 'Kezdés UTC': (T + timedelta(days=2)).isoformat(),
                  'Eredeti fogadóiroda (a splits és odds azonos irodától)': 'DraftKings',
                  'Közlő oldal neve': 'Original publisher', 'Eredeti adatforrás neve': 'DraftKings splits',
                  'Eredeti közlés HTTPS URL': 'https://example.com/source',
                  'Közzététel UTC': T.isoformat(), 'Megfigyelés UTC': T.isoformat()}
        for label, value in values.items(): self.set_text(app, label, value)
        next(x for x in app.text_area if x.label == 'Eredeti közlés szövege / pontos idézete').set_value('Synthetic reference')
        next(x for x in app.checkbox if x.label.startswith('Az eredeti forrást')).check()
        app.text_input(key='market_ticket_home').set_value('40')
        app.text_input(key='market_ticket_away').set_value('60')
        app.text_input(key='market_handle_home').set_value('70')
        app.text_input(key='market_handle_away').set_value('30')
        app.text_input(key='market_price_home').set_value('1.8')
        app.text_input(key='market_price_away').set_value('2.2')
        with patch('market_research.now', return_value=T):
            next(b for b in app.button if b.label == 'Új megfigyelés végleges mentése').click().run()
        self.assertFalse(app.exception)
        self.assertTrue(app.success)
        self.assertEqual(self.cloud.writes, 1)
        restored = self.app(); self.unlock(restored)
        self.assertFalse(restored.exception)
        self.assertEqual(len(self.cloud.state['observations']), 2)
        self.assertEqual(self.cloud.state['observations'][-1]['payload']['fixture_id'], 'fixture-new')

    def test_cloud_failure_never_shows_saved_and_does_not_offer_reset(self):
        app = self.app()
        with patch.object(self.cloud, 'load', side_effect=ValueError('fixture-secret-token')):
            self.unlock(app)
        self.assertTrue(app.error)
        self.assertFalse(app.success)
        self.assertNotIn('fixture-secret-token', str(app.error))
        self.assertFalse(any('létrehozása' in b.label for b in app.button))

    def test_application_navigation_exposes_separate_market_page(self):
        app = AppTest.from_file('streamlit_app.py', default_timeout=15)
        app.run()
        next(x for x in app.radio if x.label == 'Funkció').set_value('Piaci nyomozó').run()
        self.assertFalse(app.exception)
        self.assertEqual(app.title[0].value, 'Piaci nyomozó')
        self.assertEqual(self.cloud.loads, 0)


if __name__ == '__main__': unittest.main()
