"""Opt-in ephemeral local PostgreSQL with TLS; never uses external Secrets or data."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import importlib.util
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import unittest
import uuid

from technical_test import HOST
from technical_test_postgres import PostgresTestStore, StorageUnavailable

ENABLED = os.environ.get('FVA_RUN_LOCAL_POSTGRES_TESTS') == '1'


@unittest.skipUnless(ENABLED, 'Local TLS PostgreSQL integration not enabled')
class LocalPostgresIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='fva-synthetic-pg-')
        cls.root = Path(cls.temp.name)
        cls.bin = Path(os.environ['FVA_TEST_POSTGRES_BIN'])
        cls.data = cls.root/'data'
        def run(*args):
            return subprocess.run(args, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        cls.run_cmd = staticmethod(run)
        run(str(cls.bin/'initdb'), '-D', str(cls.data), '-A', 'trust', '-U', 'postgres')
        run('openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1',
            '-subj', '/CN=localhost', '-addext', 'subjectAltName=DNS:localhost',
            '-keyout', str(cls.root/'server.key'), '-out', str(cls.root/'server.crt'))
        os.chmod(cls.root/'server.key', 0o600)
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0)); cls.port = sock.getsockname()[1]
        with (cls.data/'postgresql.conf').open('a') as f:
            f.write(f"\nlisten_addresses='127.0.0.1'\nport={cls.port}\nunix_socket_directories='{cls.root}'\nssl=on\nssl_cert_file='{cls.root}/server.crt'\nssl_key_file='{cls.root}/server.key'\n")
        (cls.data/'pg_hba.conf').write_text('local all all trust\nhostssl all all 127.0.0.1/32 trust\n')
        cls.start()
        cls.addClassCleanup(cls.cleanup)
        import psycopg
        cls.admin = dict(host='localhost', port=cls.port, dbname='postgres', user='postgres',
                         sslmode='verify-full', sslrootcert=str(cls.root/'server.crt'))
        with psycopg.connect(**cls.admin, autocommit=True) as db:
            db.execute('CREATE ROLE fva_test_app LOGIN NOINHERIT')
            db.execute('REVOKE CREATE ON SCHEMA public FROM PUBLIC')
            db.execute((Path(__file__).resolve().parents[1]/'sql/technical_test_postgres.sql').read_text())
        cls.config = dict(host='localhost', port=cls.port, dbname='postgres', user='fva_test_app',
                          password='synthetic-unused-trust-auth', sslrootcert=str(cls.root/'server.crt'))

    @classmethod
    def start(cls):
        cls.run_cmd(str(cls.bin/'pg_ctl'), '-D', str(cls.data), '-l', str(cls.root/'server.log'), '-w', 'start')

    @classmethod
    def cleanup(cls):
        cls.run_cmd(str(cls.bin/'pg_ctl'), '-D', str(cls.data), '-m', 'fast', '-w', 'stop')
        cls.temp.cleanup()

    def store(self, **overrides):
        return PostgresTestStore({'technical_test_postgres': {**self.config, **overrides}},
                                 url='https://' + HOST, enabled='1')

    def fields(self):
        clock = datetime.now(timezone.utc)
        return dict(fixture=uuid.uuid4().hex, home='A', away='B', kickoff=(clock+timedelta(days=1)).isoformat(),
                    observed_at=(clock-timedelta(hours=1)).isoformat(), prices=dict(home=2.3, draw=3.2, away=3.0))

    def test_parallel_append_retry_rollback_and_privileges(self):
        fields = self.fields(); key = uuid.uuid4()
        before = len(self.store().load()['observations'])
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lambda _: self.store().save_match(request_id=key, **fields), range(8)))
        state = self.store().load()
        self.assertEqual(len(state['observations']), before+1)
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lambda _: self.store().save_match(request_id=uuid.uuid4(), **self.fields()), range(8)))
        self.assertEqual(len(self.store().load()['observations']), before+9)
        with self.assertRaises(StorageUnavailable):
            self.store().save_match(request_id=key, **{**fields, 'home': 'C'})
        self.assertEqual(len(self.store().load()['observations']), before+9)
        for sql in ('DELETE FROM fva_technical_test.events',
                    'UPDATE fva_technical_test.events SET fixture_id=fixture_id'):
            with self.assertRaises(StorageUnavailable):
                with self.store()._connection() as cur:
                    cur.execute(sql)
        # A transaction interrupted after INSERT must leave neither event nor retry key.
        import psycopg
        with psycopg.connect(**self.admin) as db:
            with self.assertRaises(RuntimeError):
                with db.transaction():
                    db.execute("DELETE FROM fva_technical_test.events")
                    raise RuntimeError('synthetic rollback')
        self.assertEqual(len(self.store().load()['observations']), before+9)

    def test_new_instance_and_database_restart_preserve_exact_history(self):
        self.store().save_match(request_id=uuid.uuid4(), **self.fields())
        expected = self.store().load()
        self.assertEqual(self.store().load(), expected)
        self.run_cmd(str(self.bin/'pg_ctl'), '-D', str(self.data), '-m', 'fast', '-w', 'stop')
        with self.assertRaises(StorageUnavailable):
            self.store().load()
        self.start()
        self.assertEqual(self.store().load(), expected)

    def test_wrong_tls_ca_or_database_identity_blocks_access(self):
        with self.assertRaises(StorageUnavailable):
            self.store(sslrootcert=str(self.root/'missing-ca.crt')).load()
        import psycopg
        with psycopg.connect(**self.admin) as db:
            db.execute("UPDATE fva_technical_test.identity SET format='foreign'")
        try:
            with self.assertRaises(StorageUnavailable):
                self.store().load()
        finally:
            with psycopg.connect(**self.admin) as db:
                db.execute("UPDATE fva_technical_test.identity SET format='TESZT-postgres-v1'")
