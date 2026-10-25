"""Dedicated synthetic TESZT PostgreSQL adapter. No environment/file/SQLite fallback."""
from copy import deepcopy
from contextlib import contextmanager
import json
import os
import re
import time
import uuid

from forecast_journal import canonical, digest, utc
from market_research import empty_state, _append, normalize_prices
from technical_test import APP, permitted, observation, _validate, _stamp

SCHEMA = 'fva_technical_test'
IDENTITY = 'TESZT-postgres-v1'


class StorageUnavailable(ValueError):
    """Safe public error; driver exceptions may contain credentials and stay private."""
    retryable = False


class PostgresTestStore:
    def __init__(self, secrets, *, url, enabled):
        if not permitted(url, enabled):
            raise StorageUnavailable('TESZT application identity required')
        try:
            config = secrets['technical_test_postgres']
            # Explicit parameters only: never accept a DSN, service file or env credentials.
            keys = ('host', 'port', 'dbname', 'user', 'password', 'sslrootcert')
            self._params = {k: config[k] for k in keys}
            if any(not str(v).strip() for v in self._params.values()):
                raise ValueError()
            if any(not isinstance(self._params[k], str) for k in keys if k != 'port'):
                raise ValueError()
            if not re.fullmatch(r'[A-Za-z0-9.-]+', self._params['host']):
                raise ValueError()
            if any(not re.fullmatch(r'[A-Za-z0-9_-]+', self._params[k]) for k in ('dbname', 'user')):
                raise ValueError()
            if type(self._params['port']) not in (str, int) or not 1 <= int(self._params['port']) <= 65535:
                raise ValueError()
            self._params.update(sslmode='verify-full', connect_timeout=5,
                                passfile='/dev/null',
                                application_name=APP, options='-c timezone=UTC -c statement_timeout=10000 -c lock_timeout=5000')
        except Exception:
            raise StorageUnavailable('Missing or invalid TESZT PostgreSQL Secrets') from None

    @contextmanager
    def _connection(self):
        try:
            # Reject inherited libpq selectors rather than reading credentials or
            # allowing a service/hostaddr setting to redirect the dedicated DB.
            if any(name.startswith('PG') for name in os.environ):
                raise StorageUnavailable('Inherited libpq configuration forbidden')
            import psycopg
            with psycopg.connect(**self._params) as db:
                if not db.pgconn.ssl_in_use:
                    raise StorageUnavailable('TLS required')
                with db.cursor() as cur:
                    cur.execute('SELECT current_database(), current_user, app, format FROM '
                                'fva_technical_test.identity WHERE id=1')
                    if cur.fetchall() != [(self._params['dbname'], self._params['user'], APP, IDENTITY)]:
                        raise StorageUnavailable('Foreign TESZT database')
                    yield cur
        except Exception as exc:
            error = StorageUnavailable('TESZT PostgreSQL operation unavailable')
            error.retryable = (getattr(exc, 'sqlstate', None) in ('40001', '40P01', '55P03')
                               or isinstance(exc, psycopg.OperationalError)) if 'psycopg' in locals() else False
            raise error from None

    @staticmethod
    def _read(cur):
        state = empty_state()
        cur.execute('SELECT kind, entry FROM fva_technical_test.events ORDER BY seq')
        for kind, entry in cur.fetchall():
            if kind not in ('observations', 'results'):
                raise ValueError('Foreign event')
            state[kind].append(entry if isinstance(entry, dict) else json.loads(entry))
        return _validate(state)

    def load(self):
        with self._connection() as cur:
            # Same lock as writers: identity + complete chain form a consistent snapshot.
            cur.execute('SELECT id FROM fva_technical_test.identity WHERE id=1 FOR SHARE')
            return self._read(cur)

    def _change(self, kind, request, key, build):
        key = str(uuid.UUID(str(key)))
        fingerprint = digest({'kind': kind, 'request': request})
        # Retry only transaction aborts and ambiguous connection failures. Every attempt
        # reuses the same key; a committed request is never appended twice.
        for attempt in range(3):
            try:
                return self._attempt(kind, request, key, fingerprint, build)
            except StorageUnavailable as exc:
                if not exc.retryable or attempt == 2:
                    raise
                time.sleep(0.05 * (attempt + 1))

    def _attempt(self, kind, request, key, fingerprint, build):
        with self._connection() as cur:
            cur.execute('SELECT id FROM fva_technical_test.identity WHERE id=1 FOR UPDATE')
            state = self._read(cur)
            cur.execute('SELECT request_hash FROM fva_technical_test.events WHERE request_id=%s', (key,))
            existing = cur.fetchone()
            if existing:
                if existing[0] != fingerprint:
                    raise ValueError('Idempotency key reused with different input')
                return state
            cur.execute('SELECT fva_technical_test.reserve_recording_time()')
            clock = cur.fetchone()[0].isoformat()
            payload = build(state, clock)
            updated = _validate(_append(state, kind, payload))
            entry = updated[kind][-1]
            cur.execute('INSERT INTO fva_technical_test.events '
                        '(request_id, request_hash, kind, fixture_id, observed_at, recorded_at, entry) '
                        'VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb)',
                        (key, fingerprint, kind, payload['fixture_id'],
                         payload['source']['observed_at'] if kind == 'observations' else payload['ended_at'],
                         clock, canonical(entry)))
            return updated

    def save_match(self, *, request_id, **fields):
        record = observation(**fields)
        def build(state, clock):
            p = deepcopy(record)
            p['recorded_at'] = clock
            p['prospective'] = utc(clock) < utc(p['kickoff'])
            for snapshot in p['odds']:
                snapshot['original_prices'] = deepcopy(snapshot['prices'])
                snapshot['original_convention'] = 'decimal'
                snapshot['prices'], snapshot['fair_probabilities'], snapshot['overround'] = normalize_prices(snapshot['prices'])
            return p
        return self._change('observations', record, request_id, build)

    def save_result(self, fixture_id, *, request_id, home_goals, away_goals, ended_at):
        if any(type(v) is not int or not 0 <= v <= 100 for v in (home_goals, away_goals)):
            raise ValueError('Invalid TESZT score')
        request = dict(fixture_id=fixture_id, home_goals=home_goals, away_goals=away_goals, ended_at=_stamp(ended_at))
        def build(state, clock):
            p = next(e['payload'] for e in state['observations'] if e['payload']['fixture_id'] == fixture_id)
            winner = 'home' if home_goals > away_goals else 'draw' if home_goals == away_goals else 'away'
            return dict(sport='football', fixture_id=fixture_id, market='1X2', line='none',
                        actual_kickoff=p['kickoff'], ended_at=request['ended_at'], confirmed=True,
                        score=f'{home_goals}-{away_goals}', source_url='https://example.invalid/TESZT',
                        explanation='TESZT synthetic settlement', recorded_at=clock,
                        settlement={o: 'win' if o == winner else 'loss' for o in p['outcomes']})
        return self._change('results', request, request_id, build)
