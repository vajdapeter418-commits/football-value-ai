"""Optional market research: immutable evidence, no scraping, tips or model changes."""
from copy import deepcopy
import csv
from datetime import timedelta
import io
import json
import math
from urllib.parse import urlsplit

from forecast_journal import canonical, digest, now, utc

FORMAT = 'market-research-v1'
ZERO = '0' * 64
MAX_BYTES = 2 * 1024 * 1024
COLLECTIONS = ('observations', 'results', 'protocols')


def empty_state():
    return {'format': FORMAT, **{key: [] for key in COLLECTIONS}}


def text(value, name, maximum=4000):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError('Invalid ' + name)
    return value.strip()


def https(value):
    parsed = urlsplit(text(value, 'source URL'))
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('HTTPS source URL required')
    return value


def number(value, low, high):
    if isinstance(value, bool):
        raise ValueError('Boolean is not a measurement')
    result = float(value)
    if not math.isfinite(result) or not low <= result <= high:
        raise ValueError('Measurement outside range')
    return result


def decimal_odds(value, convention='decimal'):
    value = number(value, -1000000, 1000000)
    if convention == 'american':
        if abs(value) < 100:
            raise ValueError('Invalid American odds')
        value = 1 + (value / 100 if value > 0 else 100 / -value)
    elif convention != 'decimal':
        raise ValueError('Unsupported odds convention')
    if value <= 1:
        raise ValueError('Decimal odds must exceed one')
    return value


def normalize_prices(prices):
    if not isinstance(prices, dict) or not 2 <= len(prices) <= 20:
        raise ValueError('A complete mutually exclusive market is required')
    decimals = {text(k, 'outcome', 100): decimal_odds(v) for k, v in sorted(prices.items())}
    if len(decimals) != len(prices):
        raise ValueError('Duplicate outcome')
    total = sum(1 / v for v in decimals.values())
    return decimals, {k: (1 / v) / total for k, v in decimals.items()}, total - 1


def source_valid(source):
    for key in ('publisher', 'original_bookmaker', 'original_source', 'original_text'):
        text(source[key], key)
    https(source['url'])
    if source['verification'] not in ('manual_verified', 'unverified'):
        raise ValueError('Invalid verification status')
    if source['permission'] not in ('manual_reference', 'licensed_api', 'unknown', 'denied'):
        raise ValueError('Invalid permission status')
    if source['fetch_status'] not in ('manual', 'ok', 'not_available', 'error'):
        raise ValueError('Invalid fetch status')
    if source['permission'] == 'licensed_api':
        https(source['license_url'])
    utc(source['published_at'])
    utc(source['observed_at'])
    if utc(source['published_at']) > utc(source['observed_at']):
        raise ValueError('Publication after observation')


def available(p):
    s = p['source']
    return (s['verification'] == 'manual_verified'
            and s['permission'] in ('manual_reference', 'licensed_api')
            and s['fetch_status'] in ('manual', 'ok'))


def _observation(p):
    for key in ('fixture_id', 'home', 'away', 'sport', 'market', 'line', 'bookmaker'):
        # line identifies the handicap/total; use 'none' for markets without a line.
        if text(p[key], key, 200) != p[key]:
            raise ValueError('Identity fields must be trimmed')
    if p['home'] == p['away']:
        raise ValueError('Teams must differ')
    kickoff, recorded = utc(p['kickoff']), utc(p['recorded_at'])
    source_valid(p['source'])
    if utc(p['source']['observed_at']) > recorded:
        raise ValueError('Future observation')
    if p['bookmaker'].casefold() != p['source']['original_bookmaker'].casefold():
        raise ValueError('Splits and odds must refer to the same original bookmaker')
    # Import never turns a late historical record into a prospective snapshot.
    if p['prospective'] is not (recorded < kickoff):
        raise ValueError('Invalid prospective flag')
    outcomes = p['outcomes']
    if not isinstance(outcomes, list) or not 2 <= len(outcomes) <= 20:
        raise ValueError('Complete outcome list required')
    if len(set(outcomes)) != len(outcomes):
        raise ValueError('Duplicate outcome')
    for outcome in outcomes:
        if text(outcome, 'outcome', 100) != outcome:
            raise ValueError('Outcome names must be trimmed')
    if not isinstance(p['shares'], dict) or set(p['shares']) != set(outcomes):
        raise ValueError('Shares must identify every outcome; missing values are null')
    for metric in ('tickets', 'handle'):
        values = []
        for outcome in outcomes:
            share = p['shares'][outcome]
            value, origin = share[metric], share[metric + '_origin']
            if value is None:
                if origin != 'unavailable':
                    raise ValueError('Missing percentage must be unavailable')
            else:
                number(value, 0, 100)
                if origin not in ('reported', 'calculated_complement'):
                    raise ValueError('Percentage provenance required')
                values.append(value)
                if origin == 'calculated_complement':
                    others = [p['shares'][x] for x in outcomes if x != outcome]
                    if (len(outcomes) != 2 or others[0][metric] is None
                            or others[0][metric + '_origin'] != 'reported'
                            or abs(value + others[0][metric] - 100) > 1e-8):
                        raise ValueError('Complement needs a reported two-way opposite')
        if sum(values) > 100.000001:
            raise ValueError('Percentages exceed 100')
        if len(values) == len(outcomes) and abs(sum(values) - 100) > 1e-6:
            raise ValueError('Complete percentages must sum to 100')
    previous = None
    for snapshot in p['odds']:
        source_valid(snapshot['source'])
        at = utc(snapshot['at'])
        if (at > utc(snapshot['source']['observed_at']) or at > recorded
                or at >= kickoff or (previous is not None and at <= previous)
                or utc(snapshot['source']['observed_at']) > recorded):
            raise ValueError('Invalid odds chronology')
        if snapshot['source']['original_bookmaker'].casefold() != p['bookmaker'].casefold():
            raise ValueError('Bookmaker mismatch')
        if snapshot['kind'] not in ('opening', '12h', 'closing', 'snapshot'):
            raise ValueError('Invalid odds marker')
        if snapshot['kind'] == '12h' and abs((kickoff-at).total_seconds()-43200) > 900:
            raise ValueError('12h marker must be within 15 minutes of kickoff minus 12h')
        prices, probabilities, margin = normalize_prices(snapshot['prices'])
        if set(prices) != set(outcomes):
            raise ValueError('Odds must cover the complete same market')
        original = {k: decimal_odds(v, snapshot['original_convention'])
                    for k, v in snapshot['original_prices'].items()}
        if original != prices:
            raise ValueError('Original and normalized odds disagree')
        if probabilities != snapshot['fair_probabilities'] or margin != snapshot['overround']:
            raise ValueError('Invalid normalized odds')
        previous = at
    for news in p['news']:
        source_valid(news['source'])
        if (news['kind'] not in ('injury', 'rotation', 'lineup', 'other')
                or news['certainty'] not in ('fact', 'assumption')
                or utc(news['source']['observed_at']) > recorded
                or utc(news['source']['observed_at']) >= kickoff):
            raise ValueError('Invalid team news')
        text(news['text'], 'news')
    for key in ('hypothesis', 'explanation'):
        if not isinstance(p[key], str) or len(p[key]) > 4000:
            raise ValueError('Invalid research note')


def market_key(p):
    return (p['sport'].casefold(), p['fixture_id'], p['market'].casefold(),
            p['line'].casefold(), p['bookmaker'].casefold())


def fixture_key(p):
    return p['sport'].casefold(), p['fixture_id']


def _result(p, observations):
    text(p['fixture_id'], 'fixture'); text(p['sport'], 'sport')
    https(p['source_url']); text(p['explanation'], 'settlement explanation')
    related = [o for o in observations if fixture_key(o) == fixture_key(p)
               and o['market'].casefold() == p['market'].casefold()
               and o['line'].casefold() == p['line'].casefold()]
    if not related:
        raise ValueError('No matching observation')
    if p['confirmed'] is not True or utc(p['ended_at']) < utc(p['actual_kickoff']):
        raise ValueError('Confirmed completion required')
    if utc(p['recorded_at']) < utc(p['ended_at']):
        raise ValueError('Result precedes completion')
    text(p['score'], 'final score')
    for o in related:
        if set(p['settlement']) != set(o['outcomes']):
            raise ValueError('Settlement must cover every outcome')
    if any(v not in ('win', 'loss', 'push', 'void', 'half_win', 'half_loss')
           for v in p['settlement'].values()):
        raise ValueError('Invalid settlement')


def _protocol(p):
    text(p['name'], 'protocol name', 200)
    text(p['manifest'], 'prospective selection manifest')
    if not utc(p['recorded_at']) < utc(p['test_start']) < utc(p['test_end']):
        raise ValueError('Register the protocol before the test period')
    number(p['gap_threshold'], 0, 100)
    number(p['movement_threshold'], 0, 100)
    number(p['decision_hours'], 0, 168)
    number(p['max_age_hours'], 0.01, 720)


def validate_state(state):
    if set(state) != {'format', *COLLECTIONS} or state['format'] != FORMAT:
        raise ValueError('Invalid market archive format')
    observations = []
    for key in COLLECTIONS:
        previous = ZERO
        last = None
        seen = set()
        for entry in state[key]:
            p = entry['payload']; recorded = utc(p['recorded_at'])
            if (entry['previous_hash'] != previous
                    or entry['entry_hash'] != digest({'previous_hash': previous, 'payload': p})
                    or entry['entry_hash'] in seen or (last is not None and recorded < last)):
                raise ValueError('Invalid or backdated market history')
            if key == 'observations':
                _observation(p)
                # A provider fixture identity cannot silently change teams or scheduled start.
                for old in observations:
                    if fixture_key(old) == fixture_key(p) and any(
                            old[k] != p[k] for k in ('home', 'away', 'kickoff')):
                        raise ValueError('Conflicting fixture identity')
                observations.append(p)
            elif key == 'results':
                _result(p, observations)
            else:
                _protocol(p)
            seen.add(entry['entry_hash']); previous = entry['entry_hash']; last = recorded
    return state


def _append(state, key, payload):
    validate_state(state)
    updated = deepcopy(state)
    previous = updated[key][-1]['entry_hash'] if updated[key] else ZERO
    updated[key].append({'payload': payload, 'previous_hash': previous,
                         'entry_hash': digest({'previous_hash': previous, 'payload': payload})})
    validate_state(updated)
    if len(canonical(updated).encode()) > MAX_BYTES:
        raise ValueError('Market archive size limit')
    return updated


def append_observations(state, records):
    """Atomic batch. Recorded time is always the server clock, never the imported time."""
    if not records or len(records) > 500:
        raise ValueError('Import 1..500 records')
    updated = deepcopy(state)
    clock = utc(now()).isoformat()
    for record in records:
        p = deepcopy(record)
        if any(k in p for k in ('recorded_at', 'prospective')):
            raise ValueError('Imported server timestamps are forbidden')
        p['recorded_at'] = clock
        p['prospective'] = utc(clock) < utc(p['kickoff'])
        for snapshot in p['odds']:
            convention = snapshot.pop('convention', 'decimal')
            normalized = {k: decimal_odds(v, convention) for k, v in snapshot['prices'].items()}
            snapshot['original_prices'] = deepcopy(snapshot['prices'])
            snapshot['original_convention'] = convention
            snapshot['prices'], snapshot['fair_probabilities'], snapshot['overround'] = normalize_prices(normalized)
        updated = _append(updated, 'observations', p)
    return updated


def append_result(state, record):
    if 'recorded_at' in record:
        raise ValueError('Imported server timestamp forbidden')
    return _append(state, 'results', {**deepcopy(record), 'recorded_at': utc(now()).isoformat()})


def append_protocol(state, record):
    if 'recorded_at' in record:
        raise ValueError('Imported server timestamp forbidden')
    return _append(state, 'protocols', {**deepcopy(record), 'recorded_at': utc(now()).isoformat()})


def parse_csv(raw):
    """One JSON observation per CSV row; nested data keeps explicit provenance."""
    if len(raw) > MAX_BYTES:
        raise ValueError('Import too large')
    reader = csv.DictReader(io.StringIO(raw.decode('utf-8-sig')))
    if reader.fieldnames != ['observation_json']:
        raise ValueError('Expected one observation_json CSV column')
    records = []
    for row in reader:
        if len(records) >= 500 or None in row or not row['observation_json']:
            raise ValueError('Invalid CSV row or row limit')
        records.append(json.loads(row['observation_json']))
    if not records:
        raise ValueError('Empty CSV')
    return records


def delta_pp(share):
    return None if share['handle'] is None or share['tickets'] is None else share['handle'] - share['tickets']


def source_status(p, at=None, max_age_hours=24):
    if not available(p):
        return 'nem elérhető'
    at = utc(at or now())
    age = (at - utc(p['source']['published_at'])).total_seconds() / 3600
    return 'friss' if 0 <= age <= max_age_hours else 'elavult'
