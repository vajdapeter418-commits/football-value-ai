"""Date regressions; synthetic fixtures never touch the production database."""
import ast
from datetime import datetime, timezone
from pathlib import Path
import unittest
from unittest.mock import patch

import odds_detective as detective


class DetectiveDates(unittest.TestCase):
    def test_new_investigation_defaults_to_current_utc_day(self):
        # Evaluate the actual widget default without requiring Streamlit.
        tree = ast.parse((Path(__file__).parents[1] / 'detective_ui.py').read_text())
        widget = next(node for node in ast.walk(tree)
                      if isinstance(node, ast.Call)
                      and isinstance(node.func, ast.Attribute)
                      and node.func.attr == 'date_input'
                      and node.args and isinstance(node.args[0], ast.Constant)
                      and node.args[0].value == 'Mérkőzés napja (UTC)')
        default = next(kw.value for kw in widget.keywords if kw.arg == 'value')
        expression = compile(ast.Expression(default), '<date default>', 'eval')
        for instant in ('2026-10-23T00:01:00+00:00', '2026-10-24T00:01:00+00:00'):
            with self.subTest(instant=instant), patch('datetime.datetime') as clock:
                clock.now.return_value = datetime.fromisoformat(instant)
                self.assertEqual(eval(expression, {'datetime': clock, 'timezone': timezone}),
                                 datetime.fromisoformat(instant).date())
                clock.now.assert_called_once_with(timezone.utc)

    def test_offset_crosses_utc_day_boundary(self):
        self.assertTrue(detective.utc('2026-10-23T00:30:00+02:00').startswith('2026-10-22T22:30:00'))
        self.assertTrue(detective.utc('2026-10-22T23:30:00-02:00').startswith('2026-10-23T01:30:00'))

    def test_timezone_required(self):
        with self.assertRaises(ValueError):
            detective.utc('2026-10-23T12:00:00')

    def test_filter_uses_event_utc_date(self):
        events = [{'commence_time': '2026-10-23T00:30:00+02:00'},
                  {'commence_time': '2026-10-23T12:00:00Z'}]
        self.assertEqual(detective.events_on_date(events, '2026-10-23'), [events[1]])

    def test_existing_match_dates_are_preserved(self):
        store = detective.Store(':memory:')
        try:
            store.seed()
            mid = store.add_match('Test Home', 'Test Away', '2026-10-23', 'https://example.com/match')
            dates = {m['id']: m['match_date'] for m in store.matches()}
            self.assertEqual(dates[mid], '2026-10-23')
            self.assertEqual(dates['iberia-mjallby-2026-10-22'], '2026-10-22')
        finally:
            store.close()


if __name__ == '__main__':
    unittest.main()

