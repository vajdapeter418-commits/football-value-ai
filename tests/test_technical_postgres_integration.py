"""Opt-in ephemeral local PostgreSQL with TLS; never uses external Secrets or data."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
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
            db.execute('CREATE ROLE migration_schema_owner NOLOGIN')
            db.execute('REVOKE CREATE ON SCHEMA public FROM PUBLIC')
            db.execute('REVOKE TEMP ON DATABASE postgres FROM PUBLIC')
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

    def test_migration_preflight_and_atomic_preservation(self):
        import psycopg
        from psycopg import sql
        migration = (Path(__file__).resolve().parents[1]/'sql/technical_test_postgres.sql').read_text()
        cases = [
            ('missing', '', True),
            ('empty', 'CREATE SCHEMA fva_technical_test', True),
            ('table', 'CREATE SCHEMA fva_technical_test; CREATE TABLE fva_technical_test.keep(x int); INSERT INTO fva_technical_test.keep VALUES(42)', False),
            ('function', 'CREATE SCHEMA fva_technical_test; CREATE FUNCTION fva_technical_test.keep() RETURNS int LANGUAGE sql AS $$SELECT 42$$', False),
            ('type', "CREATE SCHEMA fva_technical_test; CREATE TYPE fva_technical_test.keep AS ENUM ('keep')", False),
            ('owner', 'CREATE SCHEMA fva_technical_test AUTHORIZATION migration_schema_owner', False),
            ('schema_acl', 'CREATE SCHEMA fva_technical_test; GRANT USAGE ON SCHEMA fva_technical_test TO PUBLIC', False),
            ('db_create', 'GRANT CREATE ON DATABASE {db} TO fva_test_app', False),
            ('db_temp', 'GRANT TEMP ON DATABASE {db} TO PUBLIC', False),
            ('public_create', 'GRANT CREATE ON SCHEMA public TO PUBLIC', False),
            ('foreign_schema', 'CREATE SCHEMA other; GRANT USAGE ON SCHEMA other TO fva_test_app', False),
            ('column_acl', 'CREATE TABLE public.keep(x int); GRANT SELECT(x) ON public.keep TO fva_test_app', False),
            ('function_acl', 'CREATE FUNCTION public.keep() RETURNS int LANGUAGE sql AS $$SELECT 42$$', False),
            ('default_acl', 'ALTER DEFAULT PRIVILEGES GRANT SELECT ON TABLES TO fva_test_app', False),
        ]
        for label, setup, success in cases:
            with self.subTest(label=label):
                name = 'migration_' + uuid.uuid4().hex
                with psycopg.connect(**self.admin, autocommit=True) as admin:
                    admin.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
                try:
                    with psycopg.connect(**{**self.admin, 'dbname': name}, autocommit=True) as db:
                        db.execute(sql.SQL('REVOKE TEMP ON DATABASE {} FROM PUBLIC').format(sql.Identifier(name)))
                        db.execute('REVOKE CREATE ON SCHEMA public FROM PUBLIC')
                        if setup:
                            db.execute(setup.format(db=name))
                        snapshot = "SELECT classid::text,objid::text,objsubid,deptype FROM pg_depend WHERE refclassid='pg_namespace'::regclass AND refobjid=to_regnamespace('fva_technical_test') ORDER BY 1,2,3,4"
                        before = db.execute(snapshot).fetchall()
                        if success:
                            db.execute(migration)
                            self.assertEqual(db.execute('SELECT count(*) FROM fva_technical_test.identity').fetchone()[0], 1)
                            # Re-running must fail without changing initialized data.
                            with self.assertRaises(psycopg.Error):
                                db.execute(migration)
                            db.execute('ROLLBACK')
                            self.assertEqual(db.execute('SELECT count(*) FROM fva_technical_test.identity').fetchone()[0], 1)
                        else:
                            with self.assertRaises(psycopg.Error):
                                db.execute(migration)
                            db.execute('ROLLBACK')
                            self.assertEqual(db.execute(snapshot).fetchall(), before)
                            if label == 'table':
                                self.assertEqual(db.execute('SELECT x FROM fva_technical_test.keep').fetchall(), [(42,)])
                finally:
                    with psycopg.connect(**self.admin, autocommit=True) as admin:
                        admin.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(name)))

    def test_migration_rejects_role_escalation_and_app_executor(self):
        import psycopg
        migration = (Path(__file__).resolve().parents[1]/'sql/technical_test_postgres.sql').read_text()
        for change, restore in [
            ('ALTER ROLE fva_test_app INHERIT', 'ALTER ROLE fva_test_app NOINHERIT'),
            ('ALTER ROLE fva_test_app CREATEDB', 'ALTER ROLE fva_test_app NOCREATEDB'),
            ('ALTER ROLE fva_test_app CREATEROLE', 'ALTER ROLE fva_test_app NOCREATEROLE'),
            ('ALTER ROLE fva_test_app BYPASSRLS', 'ALTER ROLE fva_test_app NOBYPASSRLS'),
            ('ALTER ROLE fva_test_app REPLICATION', 'ALTER ROLE fva_test_app NOREPLICATION'),
            ('ALTER ROLE fva_test_app SUPERUSER', 'ALTER ROLE fva_test_app NOSUPERUSER'),
            ('ALTER ROLE fva_test_app NOLOGIN', 'ALTER ROLE fva_test_app LOGIN'),
            ('GRANT pg_read_all_data TO fva_test_app', 'REVOKE pg_read_all_data FROM fva_test_app'),
            ('GRANT fva_test_app TO postgres', 'REVOKE fva_test_app FROM postgres'),
        ]:
            with self.subTest(change=change), psycopg.connect(**self.admin, autocommit=True) as db:
                db.execute(change)
                try:
                    expected = 'role memberships' if change.startswith('GRANT') else 'role attributes'
                    with self.assertRaisesRegex(psycopg.Error, expected):
                        db.execute(migration)
                    db.execute('ROLLBACK')
                finally:
                    db.execute(restore)
        with psycopg.connect(**{**self.admin, 'user': 'fva_test_app'}, autocommit=True) as db:
            with self.assertRaises(psycopg.Error):
                db.execute(migration)
            db.execute('ROLLBACK')

    def test_migration_with_non_superuser_owner(self):
        import psycopg
        from psycopg import sql
        migration = (Path(__file__).resolve().parents[1]/'sql/technical_test_postgres.sql').read_text()
        for label in ('valid', 'no_database_create', 'no_schema_create', 'no_schema_usage'):
            with self.subTest(label=label):
                name = 'migration_' + uuid.uuid4().hex
                with psycopg.connect(**self.admin, autocommit=True) as admin:
                    admin.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
                try:
                    with psycopg.connect(**{**self.admin, 'dbname': name}, autocommit=True) as db:
                        db.execute(sql.SQL('REVOKE TEMP ON DATABASE {} FROM PUBLIC').format(sql.Identifier(name)))
                        db.execute('REVOKE CREATE ON SCHEMA public FROM PUBLIC')
                        db.execute('CREATE SCHEMA fva_technical_test AUTHORIZATION migration_schema_owner')
                        if label != 'no_database_create':
                            db.execute(sql.SQL('GRANT CREATE ON DATABASE {} TO migration_schema_owner').format(sql.Identifier(name)))
                        db.execute('SET ROLE migration_schema_owner')
                        if label in ('no_schema_create', 'no_schema_usage'):
                            privilege = 'CREATE' if label == 'no_schema_create' else 'USAGE'
                            db.execute(f'REVOKE {privilege} ON SCHEMA fva_technical_test FROM migration_schema_owner')
                        if label == 'valid':
                            db.execute(migration)
                            self.assertEqual(db.execute("SELECT pg_get_userbyid(relowner) FROM pg_class WHERE oid='fva_technical_test.events'::regclass").fetchone()[0], 'migration_schema_owner')
                        else:
                            expected = 'database CREATE' if label == 'no_database_create' else 'schema USAGE and CREATE'
                            with self.assertRaisesRegex(psycopg.Error, expected):
                                db.execute(migration)
                            db.execute('ROLLBACK')
                            self.assertIsNone(db.execute("SELECT to_regclass('fva_technical_test.events')").fetchone()[0])
                finally:
                    with psycopg.connect(**self.admin, autocommit=True) as admin:
                        admin.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(name)))

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
        # Fail after the adapter's real INSERT, before commit: event, clock
        # reservation and idempotency key must all roll back together.
        store = self.store(); original = store._connection
        @contextmanager
        def interrupted():
            with original() as cur:
                class CursorProxy:
                    def __getattr__(inner, name):
                        return getattr(cur, name)
                    def execute(inner, sql, args=None):
                        cur.execute(sql, args)
                        if sql.startswith('INSERT'):
                            raise RuntimeError('synthetic interruption before commit')
                yield CursorProxy()
        store._connection = interrupted
        key, fields = uuid.uuid4(), self.fields()
        with self.assertRaises(StorageUnavailable):
            store.save_match(request_id=key, **fields)
        self.assertEqual(len(self.store().load()['observations']), before+9)
        self.store().save_match(request_id=key, **fields)
        self.assertEqual(len(self.store().load()['observations']), before+10)
        # Direct app-role SQL cannot reuse a past transaction's timestamp.
        with self.assertRaises(StorageUnavailable):
            with self.store()._connection() as cur:
                cur.execute("INSERT INTO fva_technical_test.events "
                            "(request_id,request_hash,kind,fixture_id,observed_at,recorded_at,entry) "
                            "SELECT %s,request_hash,kind,fixture_id,observed_at,recorded_at,entry "
                            "FROM fva_technical_test.events LIMIT 1", (uuid.uuid4(),))
        with self.assertRaises(StorageUnavailable):
            with self.store()._connection() as cur:
                cur.execute("UPDATE fva_technical_test.identity SET recorded_at=clock_timestamp()")

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
