"""Immutable, versioned evidence and cutoff-safe features (standard library only)."""
from dataclasses import dataclass, asdict
from datetime import date, datetime, timezone
from hashlib import sha256
import json
import math
from zoneinfo import ZoneInfo

REPLAY = 'historical_results_replay'
STRICT = 'strict_asof'
BLOCKS = ('xg', 'set_piece', 'style', 'players')


def utc(t):
    if not isinstance(t, datetime) or t.tzinfo is None or t.utcoffset() is None:
        raise ValueError('Timezone-aware timestamp required')
    return t.astimezone(timezone.utc)


def budapest(t):
    return utc(t).astimezone(ZoneInfo('Europe/Budapest')).isoformat()


def digest(value):
    return sha256(json.dumps(value, sort_keys=True, default=str, allow_nan=False,
                             separators=(',', ':')).encode()).hexdigest()


@dataclass(frozen=True)
class Evidence:
    source: str
    source_record_id: str
    effective_at: datetime
    published_at: datetime
    captured_at: datetime
    version: int
    units: str
    verification: str
    raw_hash: str

    def __post_init__(self):
        for name in ('effective_at', 'published_at', 'captured_at'):
            object.__setattr__(self, name, utc(getattr(self, name)))
        if (not all((self.source, self.source_record_id, self.units, self.raw_hash))
                or self.version < 1 or self.published_at > self.captured_at):
            raise ValueError('Invalid provenance')

    def known(self, cutoff):
        return (self.verification in ('source_checked', 'verified')
                and max(self.effective_at, self.published_at, self.captured_at) < utc(cutoff))


@dataclass(frozen=True)
class Match:
    match_id: str
    league: str
    season: str
    home_id: str
    away_id: str
    match_date: date
    home_goals: int | None
    away_goals: int | None
    completed: bool = True
    regulation: bool = True
    kickoff_utc: datetime | None = None
    completed_at: datetime | None = None
    evidence: Evidence | None = None

    def __post_init__(self):
        if (not all((self.match_id, self.league, self.season, self.home_id, self.away_id))
                or self.home_id == self.away_id or type(self.match_date) is not date):
            raise ValueError('Invalid match identity/date')
        for name in ('kickoff_utc', 'completed_at'):
            if getattr(self, name) is not None:
                object.__setattr__(self, name, utc(getattr(self, name)))
        if self.kickoff_utc and self.completed_at and self.completed_at <= self.kickoff_utc:
            raise ValueError('Completion must follow kickoff')
        for g in (self.home_goals, self.away_goals):
            if g is not None and (type(g) is not int or g < 0):
                raise ValueError('Invalid regulation goal count')
        if self.completed and (self.home_goals is None or self.away_goals is None):
            raise ValueError('Completed result requires goals')

    def legacy(self):
        return self.home_id, self.away_id, self.home_goals, self.away_goals, self.match_date


def adapt_tuples(rows, league='E0', season='selected'):
    # Match identity deliberately does not depend on the label. No fabricated timestamps.
    return tuple(Match(digest((league, season, h, a, d))[:24], league, season,
                       h, a, d, hg, ag) for h, a, hg, ag, d in rows)


@dataclass(frozen=True)
class Request:
    home: str
    away: str
    league: str
    season: str
    target_date: date
    prediction_cutoff: datetime
    policy: str = REPLAY
    kickoff_utc: datetime | None = None
    model_version: str = 'team-strength-v1'

    def __post_init__(self):
        object.__setattr__(self, 'prediction_cutoff', utc(self.prediction_cutoff))
        if self.kickoff_utc is not None:
            object.__setattr__(self, 'kickoff_utc', utc(self.kickoff_utc))
            if self.prediction_cutoff > self.kickoff_utc:
                raise ValueError('Cutoff follows kickoff')
        if (self.home == self.away or not all((self.home, self.away, self.league, self.season))
                or self.policy not in (REPLAY, STRICT) or type(self.target_date) is not date):
            raise ValueError('Invalid prediction request')


@dataclass(frozen=True)
class ExtraStat:
    """Match/team metric or target-specific pre-match player assessment.

    definition and denominator are provider contracts, not free text news.
    Player ratings: larger att/def means better; expected minutes are pre-match.
    """
    match_id: str
    league: str
    season: str
    team_id: str
    venue: str
    kind: str
    value: float | None
    evidence: Evidence
    definition: str
    denominator: str
    coverage: float = 1.0
    player_id: str | None = None
    position: str | None = None

    def __post_init__(self):
        if (not all((self.match_id, self.team_id, self.definition, self.denominator))
                or self.venue not in ('H', 'A') or not 0 <= self.coverage <= 1
                or (self.value is not None and not math.isfinite(self.value))):
            raise ValueError('Invalid extra statistic')


@dataclass(frozen=True)
class Snapshot:
    request: Request
    matches: tuple[Match, ...]
    extras: tuple[ExtraStat, ...]
    snapshot_hash: str


def _latest(rows, key):
    versions = {}
    for r in rows:
        k = key(r)
        e = r.evidence
        version = e.version if e else 0
        vkey = (k, version)
        if vkey in versions and versions[vkey] != r:
            raise ValueError('Conflicting duplicate/version')
        versions[vkey] = r
    latest = {}
    for (k, version), r in versions.items():
        if k not in latest or version > (latest[k].evidence.version if latest[k].evidence else 0):
            latest[k] = r
    return tuple(latest[k] for k in sorted(latest))


def snapshot(matches, request, extras=()):
    cutoff = request.prediction_cutoff
    # Filter BEFORE deduplication/hash so future imports/labels cannot affect the snapshot.
    eligible = []
    for m in matches:
        if (m.league, m.season) != (request.league, request.season):
            continue
        if request.policy == REPLAY:
            if m.match_date >= min(request.target_date, cutoff.date()):
                continue
        elif (m.evidence is None or not m.evidence.known(cutoff)
              or m.completed_at is None or m.completed_at >= cutoff
              or m.kickoff_utc is None or m.kickoff_utc >= cutoff):
            continue
        # Select latest known version first: a corrected status can revoke completion.
        eligible.append(m)
    chosen = _latest(eligible, lambda m: m.match_id)
    chosen = tuple(m for m in chosen if m.completed and m.regulation)
    # Detect alternate IDs for the same fixture too.
    fixtures = {}
    for m in chosen:
        k = (m.league, m.season, m.match_date, m.home_id, m.away_id)
        if k in fixtures and fixtures[k].legacy() != m.legacy():
            raise ValueError('Conflicting fixture IDs')
        fixtures[k] = m
    chosen = tuple(sorted(fixtures.values(), key=lambda m: (m.match_date, m.match_id)))
    ex = _latest((s for s in extras if (s.league, s.season) == (request.league, request.season)
                  and s.evidence.known(cutoff)),
                 lambda s: (s.match_id, s.team_id, s.kind, s.player_id or ''))
    # Only eligible historical match metrics, or target player records; no other future data.
    ids = {m.match_id for m in chosen}
    ex = tuple(s for s in ex if s.match_id in ids or
               (s.kind.startswith('player_') and s.match_id == target_id(request)))
    payload = {'request': asdict(request), 'matches': [asdict(m) for m in chosen],
               'extras': [asdict(s) for s in ex]}
    return Snapshot(request, chosen, ex, digest(payload))


def target_id(r):
    return digest((r.league, r.season, r.home, r.away, r.target_date))[:24]


def effective_n(weights):
    w = tuple(weights)
    return sum(w) ** 2 / sum(x*x for x in w) if w and sum(x*x for x in w) else 0.0


def age_weight(m, r, half_life=90):
    days = ((r.prediction_cutoff - m.completed_at).total_seconds()/86400
            if r.policy == STRICT else (r.target_date - m.match_date).days)
    if days <= 0 or half_life <= 0:
        raise ValueError('Nonpositive temporal distance/half-life')
    return 2 ** (-days / half_life)


def smoothed_log_rate(values, weights, league_mean):
    if league_mean <= 0 or not math.isfinite(league_mean):
        return None
    if not values:
        return None
    return math.log((sum(w*x for w, x in zip(weights, values)) + 5*league_mean)
                    / (sum(weights)+5) / league_mean)


def _metrics(snap, kind, units, definition, denominator, half_life):
    rows = [s for s in snap.extras if s.kind == kind and s.value is not None and s.coverage == 1]
    if not rows:
        return []
    if len({s.evidence.source for s in rows}) != 1:
        raise ValueError('Mixed metric providers')
    if any((s.evidence.units, s.definition, s.denominator) != (units, definition, denominator)
           or s.value < 0 for s in rows):
        raise ValueError('Metric units/definition/denominator mismatch')
    matches = {m.match_id: m for m in snap.matches}
    out = []
    for s in rows:
        m = matches.get(s.match_id)
        if m is None:
            continue
        if s.team_id != (m.home_id if s.venue == 'H' else m.away_id):
            raise ValueError('Metric team/venue mismatch')
        out.append((s, age_weight(m, snap.request, half_life)))
    return out


def _rate(rows, team, venue):
    league = [(s.value, w) for s, w in rows if s.venue == venue]
    own = [(s.value, w) for s, w in rows if s.venue == venue and s.team_id == team]
    if not league or not own:
        return None
    mu = sum(x*w for x, w in league)/sum(w for _, w in league)
    return smoothed_log_rate([x for x, _ in own], [w for _, w in own], mu)


def _z_rates(rows):
    groups = {}
    for s, w in rows:
        groups.setdefault((s.team_id, s.venue), []).append((s.value, w))
    means = {k: sum(x*w for x, w in v)/sum(w for _, w in v) for k, v in groups.items()}
    if not means:
        return {}
    mu = sum(means.values())/len(means)
    sd = math.sqrt(sum((v-mu)**2 for v in means.values())/len(means))
    return {k: (v-mu)/sd if sd else 0.0 for k, v in means.items()}


def player_losses(snap, team):
    rows = [s for s in snap.extras if s.kind.startswith('player_') and s.team_id == team
            and s.match_id == target_id(snap.request)]
    groups = {}
    for s in rows:
        groups.setdefault((s.player_id, s.position), {})[s.kind] = s
    out = {}
    required = ('minutes', 'unavailable', 'att', 'def', 'replacement_att', 'replacement_def')
    for (pid, pos), fields in groups.items():
        values = {k: fields.get('player_'+k) for k in required}
        if not pid or pos not in ('GK', 'DEF', 'MID', 'FWD'):
            continue
        if any(s is None or s.value is None or s.coverage != 1 for s in values.values()):
            out[pos] = None
            continue
        if (any(s.definition != 'higher_is_better_v1' or s.denominator != 'pre_match'
                for s in values.values())
                or len({s.evidence.source for s in values.values()}) != 1):
            raise ValueError('Player assessment definition mismatch')
        expected_units = {'minutes': 'minutes', 'unavailable': 'probability'}
        if any(s.evidence.units != expected_units.get(k, 'rating') for k, s in values.items()):
            raise ValueError('Player units mismatch')
        v = {k: s.value for k, s in values.items()}
        # FPL chance and actual played minutes are intentionally not recognised fields.
        if not 0 <= v['minutes'] <= 90 or v['unavailable'] not in (0, 1):
            out[pos] = None
            continue
        if pos not in out:
            out[pos] = (0.0, 0.0)
        if out[pos] is not None:
            scale = v['minutes']/90 * v['unavailable']
            out[pos] = (out[pos][0] + scale*(v['att']-v['replacement_att']),
                        out[pos][1] + scale*(v['def']-v['replacement_def']))
    return out


def features(snap, blocks=(), half_life=90):
    """Same role semantics in home/away vectors; unknown remains None until scaling.

    Total xG is replaced by open-play xG when set pieces are also enabled.
    Provider must supply the disjoint open-play definition; never subtract guesses.
    """
    if set(blocks)-set(BLOCKS):
        raise ValueError('Unknown feature block')
    h, a = {}, {}
    r = snap.request
    for block in blocks:
        if block in ('xg', 'set_piece'):
            prefix = ('open_xg' if 'set_piece' in blocks else 'total_xg') if block == 'xg' else 'set_xg'
            att = _metrics(snap, prefix+'_for', 'xG/match', prefix+'_v1', 'match', half_life)
            deff = _metrics(snap, prefix+'_against', 'xG/match', prefix+'_v1', 'match', half_life)
            for out, own, opp, venue, other in ((h,r.home,r.away,'H','A'),(a,r.away,r.home,'A','H')):
                out[block+'.att'] = _rate(att, own, venue)
                out[block+'.allowed'] = _rate(deff, opp, other)
        elif block == 'style':
            spec = (('ppda','passes/defensive_action','ppda_v1','defensive_action'),
                    ('pressured_losses','losses/pressured_possession','pressured_losses_v1','pressured_possession'),
                    ('counter_for','xG/90','counter_v1','90_minutes'),
                    ('counter_against','xG/90','counter_v1','90_minutes'))
            zs = [_z_rates(_metrics(snap,*s,half_life)) for s in spec]
            for out, own, opp, venue, other in ((h,r.home,r.away,'H','A'),(a,r.away,r.home,'A','H')):
                p,l,c,d = zs
                out['style.press_loss'] = (-p[own,venue]*l[opp,other]
                    if (own,venue) in p and (opp,other) in l else None)
                out['style.counter'] = (c[own,venue]*d[opp,other]
                    if (own,venue) in c and (opp,other) in d else None)
        else:
            losses = {t: player_losses(snap,t) for t in (r.home,r.away)}
            for out, own, opp in ((h,r.home,r.away),(a,r.away,r.home)):
                for pos in ('GK','DEF','MID','FWD'):
                    x,y = losses[own].get(pos),losses[opp].get(pos)
                    out['players.'+pos+'.own_att_loss'] = x[0] if x is not None else None
                    out['players.'+pos+'.opp_def_loss'] = y[1] if y is not None else None
    return h,a


@dataclass(frozen=True)
class Scaler:
    # Immutable training artifact, including temporal boundary and feature schema.
    columns: tuple[str, ...]
    means: tuple[float, ...]
    stds: tuple[float, ...]
    trained_before: datetime
    version: str = 'features-v1'

    @classmethod
    def fit(cls, rows, trained_before):
        names = tuple(sorted({k for row in rows for k in row}))
        means, stds = [], []
        for k in names:
            vals = [row[k] for row in rows if row.get(k) is not None]
            if any(not math.isfinite(x) for x in vals):
                raise ValueError('Invalid scaler input')
            mu = sum(vals)/len(vals) if vals else 0.0
            means.append(mu)
            stds.append(math.sqrt(sum((v-mu)**2 for v in vals)/len(vals)) if vals else 0.0)
        return cls(names, tuple(means), tuple(stds), utc(trained_before))

    def transform(self, row, cutoff):
        if self.trained_before >= utc(cutoff):
            raise ValueError('Scaler not strictly earlier than cutoff')
        values, unknown = [], []
        for k, mu, sd in zip(self.columns,self.means,self.stds):
            x = row.get(k)
            unknown.append(x is None)
            values.append(0.0 if x is None or sd == 0 else max(-3.0,min(3.0,(x-mu)/sd)))
        return tuple(values), tuple(unknown)
