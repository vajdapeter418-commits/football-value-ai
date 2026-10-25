"""Offline-only TESZT storage. Never opens application databases or cloud archives."""
from copy import deepcopy
from contextlib import closing, contextmanager
import json
import os
from pathlib import Path
import re
import sqlite3
from urllib.parse import urlsplit

from market_research import append_observations, append_result, empty_state, validate_state

APP = 'football-value-ai-market-test'
HOST = APP + '.streamlit.app'
FORMAT = 'TESZT-isolated-market-v1'


def permitted(url, enabled):
    try:
        p = urlsplit(url)
        return enabled == '1' and p.scheme == 'https' and p.netloc == HOST
    except (TypeError, ValueError):
        return False


def _stamp(value):
    from forecast_journal import utc
    return utc(value).isoformat()


def observation(*, fixture, home, away, kickoff, observed_at, prices):
    """Only structured, synthetic input; no URLs, credentials, imports or raw payloads."""
    for value in (fixture, home, away):
        if not isinstance(value, str) or not re.fullmatch(r'[\w -]{1,60}', value):
            raise ValueError('Invalid TESZT identity')
    if home == away or set(prices) != {'home', 'draw', 'away'}:
        raise ValueError('Invalid TESZT fixture or complete 1X2 prices')
    at = _stamp(observed_at)
    source = dict(publisher='TESZT', original_source='TESZT manual synthetic',
                  original_bookmaker='TESZT', url='https://example.invalid/TESZT',
                  published_at=at, observed_at=at, original_text='TESZT synthetic input',
                  verification='manual_verified', permission='manual_reference', fetch_status='manual')
    return dict(fixture_id='TESZT-' + fixture, home='TESZT ' + home, away='TESZT ' + away,
                sport='football', market='1X2', line='none', bookmaker='TESZT',
                kickoff=_stamp(kickoff), outcomes=['home', 'draw', 'away'], source=source,
                shares={o: dict(tickets=None, tickets_origin='unavailable', handle=None,
                                handle_origin='unavailable') for o in prices},
                odds=[dict(at=at, kind='snapshot', prices=deepcopy(prices), source=deepcopy(source))],
                news=[], hypothesis='TESZT', explanation='TESZT')


def _validate(state):
    validate_state(state)
    if state['protocols']:
        raise ValueError('TESZT protocols unsupported')
    for entry in state['observations']:
        p = entry['payload']
        if (not p['fixture_id'].startswith('TESZT-') or
                not all(p[k].startswith('TESZT ') for k in ('home', 'away')) or
                p['bookmaker'] != 'TESZT' or p['source']['url'] != 'https://example.invalid/TESZT'):
            raise ValueError('Non-TESZT data forbidden')
    return state


class TestStore:
    __test__ = False

    def __init__(self, root, *, url, enabled):
        if not permitted(url, enabled):
            raise ValueError('TESZT application identity required')
        self.root = Path(root)
        # A new dedicated directory is mandatory. No fallback and no DB path override.
        if (not self.root.is_absolute() or self.root.name != APP or
                self.root != self.root.resolve() or
                Path(__file__).resolve().parent in self.root.parents or
                any(p.is_symlink() for p in (self.root, *self.root.parents))):
            raise ValueError('Dedicated absolute TESZT directory required')
        marker = self.root / 'TESZT-ONLY'
        if not self.root.exists():
            self.root.mkdir(mode=0o700, parents=False)
            with marker.open('x', encoding='utf-8') as handle:
                handle.write(FORMAT)
        if (marker.is_symlink() or not marker.is_file() or
                marker.stat().st_nlink != 1 or marker.read_text(encoding='utf-8') != FORMAT):
            raise ValueError('Unrecognized TESZT directory; no files changed')
        self.path = self.root / 'TESZT.sqlite3'
        self._check_paths()
        if self.path.exists():
            # Inspect in read-only mode before any DDL/write.
            self.load()
        else:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(fd)
            with self._connect() as db:
                db.execute('CREATE TABLE technical_test(id INTEGER PRIMARY KEY CHECK(id=1), '
                           'format TEXT NOT NULL, app TEXT NOT NULL, state TEXT NOT NULL)')
                db.execute('INSERT INTO technical_test VALUES(1,?,?,?)',
                           (FORMAT, APP, json.dumps(empty_state())))

    def _check_paths(self):
        allowed = {'TESZT-ONLY', 'TESZT.sqlite3', 'TESZT.sqlite3-journal'}
        if (self.root != self.root.resolve() or self.root.stat().st_mode & 0o022 or
                any(p.name not in allowed or p.is_symlink() or not p.is_file() or
                    p.stat().st_nlink != 1 for p in self.root.iterdir()) or
                (self.root / 'TESZT-ONLY').read_text(encoding='utf-8') != FORMAT):
            raise ValueError('Foreign, linked or unprotected TESZT directory')

    @contextmanager
    def _connect(self, *, readonly=False):
        self._check_paths()
        mode = 'ro' if readonly else 'rw'
        with closing(sqlite3.connect(self.path.as_uri() + '?mode=' + mode, uri=True, timeout=10)) as db:
            with db:
                yield db

    @staticmethod
    def _read(db):
        tables = db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        if tables != [('technical_test',)]:
            raise ValueError('Foreign database forbidden')
        rows = db.execute('SELECT format, app, state FROM technical_test').fetchall()
        if len(rows) != 1 or rows[0][:2] != (FORMAT, APP):
            raise ValueError('Invalid TESZT database')
        return _validate(json.loads(rows[0][2]))

    def load(self):
        with self._connect(readonly=True) as db:
            return self._read(db)

    def _change(self, mutator):
        with self._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            old = self._read(db)
            updated = _validate(mutator(old))
            db.execute('UPDATE technical_test SET state=? WHERE id=1',
                       (json.dumps(updated, allow_nan=False),))
        return updated

    def save_match(self, **fields):
        record = observation(**fields)
        return self._change(lambda state: append_observations(state, [record]))

    def save_result(self, fixture_id, *, home_goals, away_goals, ended_at):
        if any(type(v) is not int or not 0 <= v <= 100 for v in (home_goals, away_goals)):
            raise ValueError('Invalid TESZT score')
        def change(state):
            p = next(e['payload'] for e in state['observations'] if e['payload']['fixture_id'] == fixture_id)
            winner = 'home' if home_goals > away_goals else 'draw' if home_goals == away_goals else 'away'
            return append_result(state, dict(sport='football', fixture_id=fixture_id, market='1X2',
                line='none', actual_kickoff=p['kickoff'], ended_at=_stamp(ended_at), confirmed=True,
                score=f'{home_goals}-{away_goals}', source_url='https://example.invalid/TESZT',
                explanation='TESZT synthetic settlement',
                settlement={o: 'win' if o == winner else 'loss' for o in p['outcomes']}))
        return self._change(change)
