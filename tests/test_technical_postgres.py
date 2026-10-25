"""Synthetic unit tests; no real credentials, remote connection or production data."""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch
import uuid

from market_research import empty_state
from technical_test import HOST, APP
from technical_test_postgres import PostgresTestStore, StorageUnavailable, IDENTITY

URL = 'https://' + HOST
CONFIG = dict(host='test.invalid', port=5432, dbname='synthetic_test', user='synthetic_app',
              password='synthetic-unused', sslrootcert='/synthetic/ca.crt')
T = datetime(2030, 1, 1, tzinfo=timezone.utc)
FIELDS = dict(fixture='one', home='A', away='B', kickoff=(T+timedelta(days=1)).isoformat(),
              observed_at=(T-timedelta(hours=1)).isoformat(), prices=dict(home=2.3, draw=3.2, away=3.0))


class Cursor:
    def __init__(self):
        self.events = []
        self.key = None
    def execute(self, sql, args=None):
        self.sql = sql
        if 'WHERE request_id=' in sql:
            self.key = args[0]
        if sql.startswith('INSERT'):
            self.events.append(args)
    def fetchall(self):
        if 'current_database()' in self.sql:
            return [(CONFIG['dbname'], CONFIG['user'], APP, IDENTITY)]
        return [(e[2], e[-1]) for e in self.events]
    def fetchone(self):
        if 'reserve_recording_time()' in self.sql:
            return (T,)
        return next(((e[1],) for e in self.events if e[0] == self.key), None)


class PostgresTests(unittest.TestCase):
    def store(self):
        return PostgresTestStore({'technical_test_postgres': CONFIG}, url=URL, enabled='1')
    def harness(self):
        store, cursor = self.store(), Cursor()
        @contextmanager
        def connection():
            yield cursor
        store._connection = connection
        return store, cursor

    def test_missing_secrets_and_wrong_identity_fail_closed(self):
        for secrets in ({}, {'technical_test_postgres': {}}):
            with self.assertRaises(StorageUnavailable):
                PostgresTestStore(secrets, url=URL, enabled='1')
        with self.assertRaises(StorageUnavailable):
            PostgresTestStore({'technical_test_postgres': CONFIG}, url='https://production.invalid', enabled='1')

    def test_tls_and_explicit_credentials_only(self):
        params = self.store()._params
        self.assertEqual(params['sslmode'], 'verify-full')
        self.assertEqual(params['connect_timeout'], 5)
        self.assertNotIn('dsn', params)
        self.assertEqual(params['service'], '')
        self.assertEqual(params['passfile'], '/dev/null')

    def test_save_retry_and_db_clock(self):
        store, cursor = self.harness()
        key = uuid.uuid4()
        state = store.save_match(request_id=key, **FIELDS)
        self.assertEqual(state['observations'][0]['payload']['recorded_at'], T.isoformat())
        self.assertEqual(store.save_match(request_id=key, **FIELDS), state)
        self.assertEqual(len(cursor.events), 1)
        with self.assertRaises(ValueError):
            store.save_match(request_id=key, **{**FIELDS, 'home': 'C'})

    def test_corruption_and_fixture_mutation_rejected(self):
        store, cursor = self.harness()
        store.save_match(request_id=uuid.uuid4(), **FIELDS)
        with self.assertRaises(ValueError):
            store.save_match(request_id=uuid.uuid4(), **{**FIELDS, 'home': 'C'})
        cursor.events[0] = (*cursor.events[0][:-1], '{}')
        with self.assertRaises((ValueError, KeyError)):
            store.load()

    def test_future_observation_and_invalid_result_rejected(self):
        store, cursor = self.harness()
        with self.assertRaises(ValueError):
            store.save_match(request_id=uuid.uuid4(), **{**FIELDS, 'observed_at': (T+timedelta(hours=1)).isoformat()})
        self.assertFalse(cursor.events)
        store.save_match(request_id=uuid.uuid4(), **FIELDS)
        with self.assertRaises(ValueError):
            store.save_result('TESZT-one', request_id=uuid.uuid4(), home_goals=True, away_goals=0, ended_at=T)

    def test_retry_bounded_and_nontransient_not_retried(self):
        store = self.store()
        error = StorageUnavailable('safe'); error.retryable = True
        with patch.object(store, '_attempt', side_effect=error) as call:
            with self.assertRaises(StorageUnavailable):
                store.save_match(request_id=uuid.uuid4(), **FIELDS)
            self.assertEqual(call.call_count, 3)
        with patch.object(store, '_attempt', side_effect=StorageUnavailable('safe')) as call:
            with self.assertRaises(StorageUnavailable):
                store.save_match(request_id=uuid.uuid4(), **FIELDS)
            self.assertEqual(call.call_count, 1)

    def test_lost_commit_response_reuses_durable_request_key(self):
        store, cursor = self.harness()
        attempts = []
        @contextmanager
        def connection():
            attempts.append(1)
            yield cursor
            if len(attempts) == 1:
                error = StorageUnavailable('synthetic lost commit response')
                error.retryable = True
                raise error
        store._connection = connection
        state = store.save_match(request_id=uuid.uuid4(), **FIELDS)
        self.assertEqual(len(attempts), 2)
        self.assertEqual(len(cursor.events), 1)
        self.assertEqual(len(state['observations']), 1)

    def test_unencrypted_driver_connection_is_rejected(self):
        class Connection:
            pgconn = types.SimpleNamespace(ssl_in_use=False)
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
        driver = types.SimpleNamespace(connect=lambda **kw: Connection(), OperationalError=ConnectionError)
        with patch.dict(sys.modules, psycopg=driver):
            with self.assertRaises(StorageUnavailable):
                self.store().load()

    def test_driver_error_redacted(self):
        driver = types.SimpleNamespace(connect=lambda **kw: (_ for _ in ()).throw(RuntimeError('SECRET_SENTINEL')),
                                       OperationalError=ConnectionError)
        with patch.dict(sys.modules, psycopg=driver):
            with self.assertRaises(StorageUnavailable) as error:
                self.store().load()
        self.assertNotIn('SECRET_SENTINEL', str(error.exception))

    def test_production_entrypoint_is_isolated(self):
        root = Path(__file__).resolve().parents[1]
        self.assertNotIn('technical_test', (root/'streamlit_app.py').read_text())
        ui = (root/'technical_test_ui.py').read_text()
        self.assertNotIn('TestStore(root', ui)
        self.assertNotIn('FVA_TECH_TEST_ROOT', ui)
        self.assertIn('PostgresTestStore(st.secrets', ui)
        self.assertLess(ui.index('if not _authorized()'), ui.index('PostgresTestStore(st.secrets'))
