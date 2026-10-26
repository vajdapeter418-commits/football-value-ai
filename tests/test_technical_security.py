"""Security regressions: only synthetic temporary files, no deployed service."""
from datetime import timedelta
from pathlib import Path
import os
import subprocess
import sys
from unittest.mock import patch

import unittest
import test_technical_test as fixtures
from test_technical_test import T, URL
from technical_test import APP, TestStore, authorized


class SecurityTests(unittest.TestCase):
    setUp = fixtures.TechnicalTests.setUp
    store = fixtures.TechnicalTests.store
    fields = fixtures.TechnicalTests.fields
    save = fixtures.TechnicalTests.save
    settled = fixtures.TechnicalTests.settled
    replay = fixtures.TechnicalTests.replay

    def test_oidc_verified_allowlist_required(self):
        class User(dict):
            is_logged_in = True
        valid = User(email='Tester@Example.invalid', email_verified=True)
        self.assertTrue(authorized(valid, 'other@example.invalid, tester@example.invalid'))
        for user, allow in [(None, 'tester@example.invalid'), (valid, ''),
                            (valid, 'other@example.invalid'),
                            (User(email='tester@example.invalid'), 'tester@example.invalid'),
                            (User(email='tester@example.invalid', email_verified='true'), 'tester@example.invalid')]:
            self.assertFalse(authorized(user, allow))
        valid.is_logged_in = False
        self.assertFalse(authorized(valid, 'tester@example.invalid'))

    def test_simultaneous_first_open_and_process_writes(self):
        code = '''import sys
from datetime import datetime, timedelta, timezone
from technical_test import TestStore
s=TestStore(sys.argv[1],url=sys.argv[2],enabled='1')
t=datetime.now(timezone.utc)
s.save_match(fixture=sys.argv[3],home='A',away='B',kickoff=(t+timedelta(days=1)).isoformat(),observed_at=t.isoformat(),prices={'home':2.3,'draw':3.2,'away':3.0})
'''
        jobs = [subprocess.Popen([sys.executable, '-c', code, str(self.root), URL, str(i)],
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE) for i in range(8)]
        for job in jobs:
            out, err = job.communicate(timeout=20)
            self.assertEqual(job.returncode, 0, err.decode())
        self.assertEqual(len(self.store().load()['observations']), 8)

    def test_sqlite_never_opens_disk_path_and_failed_publish_preserves_state(self):
        store = self.store()
        saved = self.save(store)
        from technical_test import sqlite3
        connect = sqlite3.connect
        def memory_only(path, *a, **kw):
            self.assertEqual(path, ':memory:')
            return connect(path, *a, **kw)
        with patch('technical_test.sqlite3.connect', side_effect=memory_only):
            self.assertEqual(store.load(), saved)
        before = store.path.read_bytes()
        with patch('technical_test.os.replace', side_effect=OSError('synthetic disk failure')):
            with self.assertRaises(OSError):
                self.save(store, at=T + timedelta(hours=1))
        self.assertEqual(store.path.read_bytes(), before)
        self.assertEqual(store.load(), saved)
        self.assertEqual(set(os.listdir(self.root)), {'TESZT-ONLY', 'TESZT.sqlite3'})

    def test_replacement_during_read_cannot_modify_foreign_target(self):
        store = self.store()
        self.save(store)
        target = Path(self.temp.name) / 'foreign.sqlite3'
        target.write_bytes(store.path.read_bytes())
        before = target.read_bytes()
        read = store._read
        replaced = False
        def swap(db):
            nonlocal replaced
            value = read(db)
            if not replaced:
                replaced = True
                store.path.unlink()
                store.path.symlink_to(target)
            return value
        with patch.object(store, '_read', side_effect=swap):
            with self.assertRaises(ValueError): self.save(store, at=T + timedelta(hours=1))
        self.assertEqual(target.read_bytes(), before)

    def test_directory_replacement_rejected(self):
        store = self.store()
        self.save(store)
        renamed = self.root.with_name('saved-root')
        self.root.rename(renamed)
        replacement = self.store()
        self.assertEqual(replacement.load()['observations'], [])
        with self.assertRaises(ValueError): store.load()
        self.assertTrue((renamed / 'TESZT.sqlite3').is_file())

    def test_multiple_saved_snapshots_movement_and_no_late_leakage(self):
        store = self.store()
        self.save(store)
        current = {'home': 1.8, 'draw': 3.8, 'away': 4.5}
        self.save(store, at=T + timedelta(hours=6), observed_at=(T + timedelta(hours=6)).isoformat(), prices=current)
        initial = self.replay(self.settled(store))
        row = initial['rows'][0]
        self.assertEqual(initial['test_n'], 1)
        self.assertEqual(row['prices'], current)
        self.assertEqual(row['picks']['movement'], 'home')
        first = self.fields()['prices']
        expected = 100 * ((1/current['home']) / sum(1/v for v in current.values()) -
                          (1/first['home']) / sum(1/v for v in first.values()))
        self.assertAlmostEqual(row['movement_fair_pp']['home'], expected)
        late = self.save(store, at=T + timedelta(days=3),
                         observed_at=(T + timedelta(hours=7)).isoformat(),
                         prices={'home': 9., 'draw': 1.2, 'away': 9.})
        self.assertEqual(self.replay(late)['rows'], initial['rows'])
        self.assertEqual(self.replay(late)['test']['movement'], initial['test']['movement'])

    def test_production_entrypoint_has_no_test_activation_hook(self):
        text = (Path(__file__).parents[1] / 'streamlit_app.py').read_text()
        self.assertNotIn('technical_test', text)
        self.assertNotIn('FVA_TECH_TEST', text)
