"""Only temporary synthetic databases; no network or deployed applications."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from market_backtest import backtest
from technical_test import APP, HOST, FORMAT, TestStore, permitted

T = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
URL = 'https://' + HOST


class TechnicalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / APP

    def store(self):
        return TestStore(self.root, url=URL, enabled='1')

    def fields(self):
        return dict(fixture='proba-1', home='A', away='B', kickoff=(T + timedelta(days=1)).isoformat(),
                    observed_at=T.isoformat(), prices={'home': 2.3, 'draw': 3.2, 'away': 3.0})

    def save(self, store, at=T, **changes):
        with patch('market_research.now', return_value=at):
            return store.save_match(**{**self.fields(), **changes})

    def settled(self, store):
        with patch('market_research.now', return_value=T + timedelta(days=2)):
            return store.save_result('TESZT-proba-1', home_goals=1, away_goals=0,
                                     ended_at=(T + timedelta(days=1, hours=2)).isoformat())

    def replay(self, state):
        with patch('market_backtest.now', return_value=T + timedelta(days=40)):
            return backtest(state, test_start='2026-01-02T00:00:00Z', test_end='2026-02-01T00:00:00Z')

    def test_host_and_explicit_enable_fail_closed(self):
        self.assertTrue(permitted(URL + '/?page=test', '1'))
        for url in ('http://' + HOST, 'https://production.streamlit.app', '',
                    URL + '.evil.test', 'https://evil@' + HOST, 'http://localhost:8501'):
            self.assertFalse(permitted(url, '1'))
            with self.assertRaises(ValueError): TestStore(self.root, url=url, enabled='1')
        self.assertFalse(permitted(URL, None))
        self.assertFalse(self.root.exists())

    def test_save_read_and_fresh_process_restart(self):
        store = self.store()
        saved = self.save(store)
        self.assertEqual(saved, self.store().load())
        code = ('import json,sys; from technical_test import TestStore; '
                'print(json.dumps(TestStore(sys.argv[1],url=sys.argv[2],enabled="1").load(),sort_keys=True))')
        result = subprocess.run([sys.executable, '-c', code, str(self.root), URL],
                                check=True, capture_output=True, text=True)
        self.assertEqual(json.loads(result.stdout), saved)
        p = saved['observations'][0]['payload']
        self.assertEqual(p['fixture_id'], 'TESZT-proba-1')
        self.assertEqual(p['odds'][0]['prices'], self.fields()['prices'])
        self.assertEqual(p['recorded_at'], T.isoformat())

    def test_production_sentinels_unchanged_and_config_ignored(self):
        sentinel = Path(self.temp.name) / 'production.sqlite3'
        sentinel.write_bytes(b'PRODUCTION SENTINEL')
        log = Path(self.temp.name) / 'existing.log'
        log.write_bytes(b'OLD LOG SENTINEL')
        before = [p.read_bytes() for p in (sentinel, log)]
        with patch.dict(os.environ, {'ODDS_DB_PATH': str(sentinel), 'PREMATCH_ARCHIVE_DB': str(sentinel),
                                     'GITHUB_TOKEN': 'credential-sentinel'}):
            self.save(self.store())
        self.assertEqual([p.read_bytes() for p in (sentinel, log)], before)
        self.assertNotIn(b'credential-sentinel', (self.root / 'TESZT.sqlite3').read_bytes())
        self.assertEqual(set(p.name for p in self.root.iterdir()), {'TESZT-ONLY', 'TESZT.sqlite3'})

    def test_foreign_directory_database_and_links_rejected_without_changes(self):
        self.root.mkdir()
        with self.assertRaises(ValueError): self.store()
        (self.root / 'TESZT-ONLY').write_text(FORMAT)
        dbpath = self.root / 'TESZT.sqlite3'
        with sqlite3.connect(dbpath) as db: db.execute('CREATE TABLE production(x)')
        before = dbpath.read_bytes()
        with self.assertRaises(ValueError): self.store()
        self.assertEqual(dbpath.read_bytes(), before)
        dbpath.unlink()
        target = Path(self.temp.name) / 'production'
        target.write_bytes(b'KEEP')
        for link in ('symlink', 'hardlink'):
            if link == 'symlink': dbpath.symlink_to(target)
            else: os.link(target, dbpath)
            with self.assertRaises(ValueError): self.store()
            self.assertEqual(target.read_bytes(), b'KEEP')
            dbpath.unlink()

    def test_replaced_database_and_extra_tables_rejected_on_existing_store(self):
        store = self.store()
        self.save(store)
        with sqlite3.connect(store.path) as db:
            db.execute('CREATE TABLE production_log(x)')
        before = store.path.read_bytes()
        with self.assertRaises(ValueError): self.save(store)
        self.assertEqual(store.path.read_bytes(), before)
        store.path.unlink()
        target = Path(self.temp.name) / 'production.sqlite3'
        target.write_bytes(b'KEEP')
        store.path.symlink_to(target)
        with self.assertRaises(ValueError): self.save(store)
        self.assertEqual(target.read_bytes(), b'KEEP')

    def test_paths_cannot_point_inside_application_or_through_symlink(self):
        for path in (Path(APP), Path(__file__).resolve().parent.parent / APP):
            with self.assertRaises(ValueError): TestStore(path, url=URL, enabled='1')
        parent = Path(self.temp.name) / 'linked'
        parent.symlink_to(Path(self.temp.name), target_is_directory=True)
        with self.assertRaises(ValueError): TestStore(parent / APP, url=URL, enabled='1')
        self.assertFalse(self.root.exists())

    def test_concurrent_writers_preserve_both_appends(self):
        from concurrent.futures import ThreadPoolExecutor
        first = self.store()
        second = self.store()
        fields = self.fields()
        # Use real server timestamps here; monkeypatching a shared clock across threads is unsafe.
        fields.update(kickoff=(datetime.now(timezone.utc) + timedelta(days=1)).isoformat())
        with ThreadPoolExecutor(max_workers=2) as pool:
            jobs = [pool.submit(s.save_match, **{**fields, 'fixture': f'parallel-{i}'})
                    for i, s in enumerate((first, second))]
            for job in jobs:
                job.result()
        self.assertEqual(len(first.load()['observations']), 2)

    def test_invalid_write_rolls_back_and_no_backdated_recording(self):
        store = self.store()
        initial = store.load()
        for prices in ({'home': 1., 'draw': 3., 'away': 4.},
                       {'home': float('nan'), 'draw': 3., 'away': 4.}):
            with self.assertRaises(ValueError): self.save(store, prices=prices)
            self.assertEqual(store.load(), initial)
        with self.assertRaises(TypeError): self.save(store, recorded_at=T.isoformat())
        with self.assertRaises(ValueError): self.save(store, observed_at=(T + timedelta(seconds=1)).isoformat())

    def test_actual_backtest_and_late_ingestion_exclusion(self):
        store = self.store()
        self.save(store)
        state = self.settled(store)
        report = self.replay(state)
        self.assertEqual(report['test_n'], 1)
        self.assertEqual(report['rows'][0]['prices'], self.fields()['prices'])
        # Old source timestamp cannot conceal late server ingestion.
        late = self.save(store, at=T + timedelta(days=3),
                         prices={'home': 9., 'draw': 1.2, 'away': 9.})
        after = self.replay(late)
        self.assertEqual(after['rows'], report['rows'])
        self.assertEqual(after['exclusions']['late_unverified_stale_or_unavailable'], 1)

    def test_cutoff_boundary_and_future_label_separation(self):
        store = self.store()
        self.save(store, at=T + timedelta(hours=12, microseconds=1))
        report = self.replay(self.settled(store))
        self.assertEqual(report['test_n'], 0)
        # A separate correctly timed observation must not depend on its outcome label.
        other = Path(self.temp.name) / 'another'
        other.mkdir()
        other_store = TestStore(other / APP, url=URL, enabled='1')
        self.save(other_store, at=T + timedelta(hours=12))
        before = other_store.load()
        self.assertEqual(self.replay(before)['test_n'], 0)
        after = self.settled(other_store)
        self.assertEqual(before['observations'], after['observations'])
        self.assertEqual(self.replay(after)['test_n'], 1)

    def test_future_result_rejected_and_integrity_checked(self):
        store = self.store()
        self.save(store)
        before = store.load()
        with patch('market_research.now', return_value=T):
            with self.assertRaises(ValueError): store.save_result('TESZT-proba-1', home_goals=1,
                away_goals=0, ended_at=(T + timedelta(days=2)).isoformat())
        self.assertEqual(store.load(), before)
        broken = deepcopy(before)
        broken['observations'][0]['payload']['home'] = 'Real team'
        with sqlite3.connect(store.path) as db:
            db.execute('UPDATE technical_test SET state=?', (json.dumps(broken),))
        with self.assertRaises(ValueError): store.load()


if __name__ == '__main__':
    unittest.main()
