"""Offline-only TESZT storage. Never opens application databases or cloud archives."""
from copy import deepcopy
from contextlib import closing, contextmanager
import json
import fcntl
import stat
import uuid
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


def authorized(user, allowlist):
    """Only verified platform OIDC claims; no request/header/session-state identity."""
    allowed = {email.strip().casefold() for email in (allowlist or '').split(',') if email.strip()}
    try:
        return (user.is_logged_in is True and user.get('email_verified') is True
                and isinstance(user.get('email'), str)
                and user.get('email').casefold() in allowed)
    except (AttributeError, TypeError):
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


@contextmanager
def closing_fd(fd):
    try:
        yield fd
    finally:
        os.close(fd)


class TestStore:
    __test__ = False

    def __init__(self, root, *, url, enabled):
        if not permitted(url, enabled):
            raise ValueError('TESZT application identity required')
        self.root = Path(root)
        if (not self.root.is_absolute() or self.root.name != APP or
                self.root != self.root.resolve() or
                Path(__file__).resolve().parent in self.root.parents):
            raise ValueError('Dedicated absolute TESZT directory required')
        self.path = self.root / 'TESZT.sqlite3'
        # Pin every directory component without following links. The parent lock
        # serializes first creation; the root lock is shared by all processes.
        with closing_fd(self._directory(self.root.parent)) as parent:
            fcntl.flock(parent, fcntl.LOCK_EX)
            created = False
            try:
                os.mkdir(APP, mode=0o700, dir_fd=parent)
                created = True
            except FileExistsError:
                pass
            with closing_fd(os.open(APP, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                    dir_fd=parent)) as rootfd:
                self.identity = self._identity(os.fstat(rootfd))
                fcntl.flock(rootfd, fcntl.LOCK_EX)
                if created:
                    fd = os.open('TESZT-ONLY', os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                                 os.O_NOFOLLOW, 0o600, dir_fd=rootfd)
                    with os.fdopen(fd, 'wb') as handle:
                        handle.write(FORMAT.encode())
                        handle.flush()
                        os.fsync(handle.fileno())
                self._check_paths(rootfd)
                if 'TESZT.sqlite3' not in os.listdir(rootfd):
                    if not created:
                        raise ValueError('Missing TESZT database; automatic recovery forbidden')
                    with closing(sqlite3.connect(':memory:')) as db:
                        db.execute('CREATE TABLE technical_test(id INTEGER PRIMARY KEY CHECK(id=1), '
                                   'format TEXT NOT NULL, app TEXT NOT NULL, state TEXT NOT NULL)')
                        db.execute('INSERT INTO technical_test VALUES(1,?,?,?)',
                                   (FORMAT, APP, json.dumps(empty_state())))
                        db.commit()
                        self._publish(rootfd, db.serialize())
                else:
                    with self._memory(rootfd) as (db, identity):
                        self._read(db)

    @staticmethod
    def _identity(info):
        return info.st_dev, info.st_ino

    @staticmethod
    def _directory(path):
        fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
        try:
            for part in path.parts[1:]:
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd)
                fd = child
            return fd
        except BaseException:
            os.close(fd)
            raise

    def _file(self, rootfd, name):
        try:
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=rootfd)
        except OSError as exc:
            raise ValueError('Missing or linked TESZT file') from exc
        try:
            info = os.fstat(fd)
            if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or
                    info.st_uid != os.geteuid() or info.st_mode & 0o022):
                raise ValueError('Linked, foreign or unprotected TESZT file')
            return fd
        except BaseException:
            os.close(fd)
            raise

    def _check_paths(self, rootfd):
        info = os.fstat(rootfd)
        if (self._identity(info) != self.identity or info.st_uid != os.geteuid() or
                info.st_mode & 0o022 or
                any(name not in {'TESZT-ONLY', 'TESZT.sqlite3'} for name in os.listdir(rootfd))):
            raise ValueError('Foreign or replaced TESZT directory')
        with os.fdopen(self._file(rootfd, 'TESZT-ONLY'), 'rb') as handle:
            if handle.read() != FORMAT.encode():
                raise ValueError('Unrecognized TESZT directory')

    @contextmanager
    def _memory(self, rootfd):
        # SQLite never opens a filesystem path, creates a journal, or runs DDL
        # against an unchecked file. Replacement links cannot redirect writes.
        with os.fdopen(self._file(rootfd, 'TESZT.sqlite3'), 'rb') as handle:
            identity = self._identity(os.fstat(handle.fileno()))
            data = handle.read()
        with closing(sqlite3.connect(':memory:')) as db:
            db.execute('PRAGMA trusted_schema=OFF')
            db.deserialize(data)
            yield db, identity

    def _publish(self, rootfd, data):
        name = '.TESZT-pending-' + uuid.uuid4().hex
        fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o600, dir_fd=rootfd)
        try:
            with os.fdopen(fd, 'wb') as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            # The destination is replaced, never followed. Both paths are
            # relative to the pinned directory, even if its parent is renamed.
            os.replace(name, 'TESZT.sqlite3', src_dir_fd=rootfd, dst_dir_fd=rootfd)
            os.fsync(rootfd)
        finally:
            try:
                os.unlink(name, dir_fd=rootfd)
            except FileNotFoundError:
                pass

    @contextmanager
    def _connect(self, *, readonly=False):
        with closing_fd(self._directory(self.root)) as rootfd:
            fcntl.flock(rootfd, fcntl.LOCK_EX)
            self._check_paths(rootfd)
            with self._memory(rootfd) as (db, identity):
                self._read(db)
                with db:
                    yield db
                if not readonly:
                    self._check_paths(rootfd)
                    with closing_fd(self._file(rootfd, 'TESZT.sqlite3')) as current:
                        if self._identity(os.fstat(current)) != identity:
                            raise ValueError('TESZT database replaced during operation')
                    self._publish(rootfd, db.serialize())

    @staticmethod
    def _read(db):
        tables = db.execute("SELECT name FROM sqlite_master").fetchall()
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

