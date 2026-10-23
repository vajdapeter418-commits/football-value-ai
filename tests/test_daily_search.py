"""Synthetic fixtures only; no network or production database access."""
from contextlib import contextmanager
from datetime import date, datetime
import importlib
import sys
import unittest
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import odds_detective as d


@contextmanager
def ui_context():
    st = MagicMock()
    st.session_state = {}
    st.button.return_value = False
    st.form_submit_button.return_value = False
    st.rerun.side_effect = RuntimeError('rerun')
    with patch.dict(sys.modules, {'streamlit': st}):
        sys.modules.pop('detective_ui', None)
        ui = importlib.import_module('detective_ui')
        yield ui, st
    sys.modules.pop('detective_ui', None)


class DailyDates(unittest.TestCase):
    def test_today_uses_budapest_across_utc_midnight(self):
        for stamp, expected in [('2026-10-23T22:30:00+00:00', date(2026, 10, 24)),
                                ('2026-12-31T23:30:00+00:00', date(2027, 1, 1))]:
            with patch.object(d, 'datetime') as clock:
                clock.now.return_value = datetime.fromisoformat(stamp).astimezone(ZoneInfo('Europe/Budapest'))
                self.assertEqual(d.budapest_today(), expected)
                clock.now.assert_called_once_with(ZoneInfo('Europe/Budapest'))

    def test_local_day_boundaries_and_dst(self):
        for day, start, end in [('2026-10-24', '2026-10-23T22:00:00Z', '2026-10-24T22:00:00Z'),
                                ('2026-03-29', '2026-03-28T23:00:00Z', '2026-03-29T22:00:00Z'),
                                ('2026-10-25', '2026-10-24T22:00:00Z', '2026-10-25T23:00:00Z')]:
            events = [{'commence_time': start}, {'commence_time': end}]
            self.assertEqual(d.events_on_budapest_date(events, day), events[:1])
        self.assertEqual(d.budapest_time('2026-10-25T00:30:00Z').strftime('%H:%M %z'), '02:30 +0200')
        self.assertEqual(d.budapest_time('2026-10-25T01:30:00Z').strftime('%H:%M %z'), '02:30 +0100')
        with self.assertRaises(ValueError):
            d.budapest_time('2026-10-23T12:00:00')

    def test_session_keeps_manual_day_and_new_session_uses_today(self):
        with ui_context() as (ui, st), patch.object(ui, 'budapest_today', return_value=date(2026, 10, 23)) as today, patch.object(ui, 'odds_picker') as picker:
            st.date_input.side_effect = lambda *a, **k: st.session_state[k['key']]
            ui.daily_search(None)
            picker.assert_called_with(None, None, '2026-10-23')
            st.session_state['daily_match_day'] = date(2026, 10, 20)
            today.return_value = date(2026, 10, 24)
            ui.daily_search(None)
            picker.assert_called_with(None, None, '2026-10-20')
            st.session_state.clear()
            ui.daily_search(None)
            picker.assert_called_with(None, None, '2026-10-24')

    def test_default_view_does_not_open_history(self):
        with ui_context() as (ui, st), patch.object(ui, 'daily_search') as daily:
            st.radio.side_effect = lambda label, options, **kw: options[0]
            store = MagicMock()
            ui.panel(store)
            daily.assert_called_once_with(store)
            store.matches.assert_not_called()

    def test_pending_selection_applied_before_widgets(self):
        with ui_context() as (ui, st):
            st.session_state['_pending_investigation'] = 'new'
            def radio(*args, **kw):
                self.assertEqual(st.session_state['saved_investigation'], 'new')
                self.assertEqual(st.session_state['detective_view'], 'Mentett vizsgálatok / előzmények')
                raise RuntimeError('checked')
            st.radio.side_effect = radio
            with self.assertRaisesRegex(RuntimeError, 'checked'):
                ui.panel(MagicMock())

    def test_daily_picker_reuses_catalogue_and_opens_new_utc_match(self):
        with ui_context() as (ui, st), patch.object(ui, 'secret', return_value='test'), patch.object(ui, 'list_football_events') as fetch, patch.object(ui, 'list_football_leagues') as leagues, patch.object(ui, 'collect_odds') as odds:
            import hashlib
            identity = hashlib.sha256(b'test').hexdigest()
            event = {'id':'event1', 'home_team':'Test Home', 'away_team':'Test Away', 'commence_time':'2026-10-23T22:30:00Z'}
            league = {'key':'soccer_test', 'title':'Test'}
            st.session_state['_odds_catalogues'] = {'identity':identity, 'leagues':[league], 'leagues_at':'test', 'events':{'soccer_test':{'rows':[event], 'at':'test'}}}
            st.selectbox.side_effect = lambda label, options, **kw: options[0]
            store = d.Store(':memory:')
            self.addCleanup(store.close)
            store.seed()
            original = store.matches()
            ui.odds_picker(store, None, '2026-10-24')
            ui.odds_picker(store, None, '2026-10-24')
            self.assertEqual(store.matches(), original)
            fetch.assert_not_called()
            leagues.assert_not_called()
            odds.assert_not_called()
            st.button.side_effect = lambda *a, **kw: kw.get('key') == 'create_daily_investigation'
            with self.assertRaisesRegex(RuntimeError, 'rerun'):
                ui.odds_picker(store, None, '2026-10-24')
            mid = st.session_state['_pending_investigation']
            created = next(m for m in store.matches() if m['id'] == mid)
            self.assertEqual(created['match_date'], '2026-10-23')
            self.assertEqual(store.matches()[0], original[0])
            d.validate_event_binding(event, created)

    def test_manual_creation_opens_new_investigation(self):
        with ui_context() as (ui, st):
            st.radio.return_value = 'Mentett vizsgálatok / előzmények'
            st.text_input.side_effect = ['Home', 'Away', 'https://example.com/match']
            st.date_input.return_value = date(2026, 10, 24)
            st.form_submit_button.return_value = True
            store = d.Store(':memory:')
            self.addCleanup(store.close)
            store.seed()
            original = store.matches()[0]
            with self.assertRaisesRegex(RuntimeError, 'rerun'):
                ui.panel(store)
            self.assertEqual(st.session_state['_pending_investigation'], store.matches()[1]['id'])
            self.assertEqual(store.matches()[0], original)


if __name__ == '__main__':
    unittest.main()
