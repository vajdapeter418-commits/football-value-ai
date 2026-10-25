"""Fixed-rule chronological research. No forecast integration or automatic betting."""
from collections import defaultdict
from datetime import timedelta
import random
import statistics

from forecast_journal import digest, now, utc
from market_research import (available, delta_pp, fixture_key, market_key,
                             source_status, validate_state)

RULES = ('baseline', 'movement', 'gap', 'combined', 'with_news', 'high_handle', 'low_handle')
WARNINGS = [
    'Kutatási eredmény, nem fogadási tipp vagy sharp money bizonyíték.',
    'Selection bias: a kézzel kiválasztott minta nem a teljes piac; a kimaradások is számítanak.',
    'Több piac és több szabály vizsgálata növeli a véletlen találat kockázatát.',
    'A bootstrap fixture szerint csoportosít; időbeli függőséget nem fed le teljesen.',
    'A közös eredeti iroda több közlőoldalon sem független adatforrás.',
]


def _eligible_source(source, cutoff, max_age):
    return (available({'source': source}) and utc(source['observed_at']) <= cutoff
            and source_status({'source': source}, cutoff, max_age) == 'friss')


def _profit(settlement, odds):
    return {'win': odds - 1, 'loss': -1, 'push': 0, 'void': 0,
            'half_win': (odds - 1) / 2, 'half_loss': -0.5}[settlement]


def _summary(rows, rule):
    chosen = [r for r in rows if r['picks'][rule] is not None]
    returns = []
    clusters = defaultdict(list)
    paired = defaultdict(list)
    wins = losses = pushes = voids = halves = 0
    for r in chosen:
        outcome = r['picks'][rule]
        settlement = r['settlement'][outcome]
        if settlement == 'void':
            voids += 1
            continue
        gain = _profit(settlement, r['prices'][outcome])
        returns.append(gain)
        clusters[r['fixture']].append(gain)
        baseline = r['picks']['baseline']
        if r['settlement'][baseline] != 'void':
            paired[r['fixture']].append(gain - _profit(r['settlement'][baseline], r['prices'][baseline]))
        wins += settlement == 'win'
        losses += settlement == 'loss'
        pushes += settlement == 'push'
        halves += settlement in ('half_win', 'half_loss')
    # Resample fixtures, keeping each fixture's complete selections and denominators.
    def clustered_ci(groups):
        if len(groups) < 2:
            return None
        rng = random.Random(12)
        groups = list(groups.values()); samples = []
        for _ in range(500):
            sampled = [v for group in rng.choices(groups, k=len(groups)) for v in group]
            samples.append(statistics.mean(sampled))
        samples.sort()
        return [samples[12], samples[487]]
    return {'bets': len(returns), 'wins': wins, 'losses': losses, 'pushes': pushes,
            'half_settlements': halves, 'voids': voids, 'fixtures': len(clusters),
            'win_rate_decisive': wins / (wins + losses) if wins + losses else None,
            'roi_unit_stake': statistics.mean(returns) if returns else None,
            'roi_ci95_fixture_bootstrap': clustered_ci(clusters),
            'paired_delta_roi_baseline': statistics.mean([v for g in paired.values() for v in g]) if paired else None,
            'paired_delta_ci95': clustered_ci(paired)}


def backtest(state, *, test_start, test_end, gap_threshold=10, movement_threshold=2,
             decision_hours=12, max_age_hours=24, protocol_hash=None):
    validate_state(state)
    start, end = utc(test_start), utc(test_end)
    if start >= end or not 0 <= gap_threshold <= 100 or not 0 <= movement_threshold <= 100:
        raise ValueError('Invalid test boundaries or thresholds')
    if not 0 <= decision_hours <= 168 or not 0 < max_age_hours <= 720:
        raise ValueError('Invalid timing controls')
    protocol = None
    if protocol_hash:
        protocol = next((e['payload'] for e in state['protocols'] if e['entry_hash'] == protocol_hash), None)
        if protocol is None or any(protocol[k] != v for k, v in {
                'test_start': test_start, 'test_end': test_end,
                'gap_threshold': gap_threshold, 'movement_threshold': movement_threshold,
                'decision_hours': decision_hours, 'max_age_hours': max_age_hours}.items()):
            raise ValueError('Report parameters must match the frozen protocol')
    clock = utc(now())
    grouped = defaultdict(list)
    exclusions = defaultdict(int)
    for entry in state['observations']:
        p = entry['payload']; kickoff = utc(p['kickoff']); cutoff = kickoff - timedelta(hours=decision_hours)
        if (not p['prospective'] or utc(p['recorded_at']) > cutoff
                or not _eligible_source(p['source'], cutoff, max_age_hours)):
            exclusions['late_unverified_stale_or_unavailable'] += 1
            continue
        grouped[market_key(p)].append(p)
    results = defaultdict(list)
    for entry in state['results']:
        p = entry['payload']
        results[(p['sport'].casefold(), p['fixture_id'], p['market'].casefold(), p['line'].casefold())].append(p)
    development, test = [], []
    for key, observations in sorted(grouped.items()):
        latest = max(observations, key=lambda p: (utc(p['source']['observed_at']), utc(p['recorded_at']), digest(p)))
        latest_time = utc(latest['source']['observed_at'])
        tied = [p for p in observations if utc(p['source']['observed_at']) == latest_time]
        if len({digest(p['shares']) for p in tied}) > 1:
            exclusions['conflicting_splits_at_same_time'] += 1
            continue
        kickoff = utc(latest['kickoff']); cutoff = kickoff - timedelta(hours=decision_hours)
        if kickoff >= end or kickoff > clock:
            continue
        partition = 'test' if kickoff >= start else 'development'
        # For development, only labels already known before the held-out period are usable.
        label_cutoff = min(clock, start) if partition == 'development' else clock
        labels = [r for r in results[key[:4]] if utc(r['recorded_at']) < label_cutoff
                  and utc(r['ended_at']) < label_cutoff]
        if not labels:
            exclusions['pending_result'] += 1
            continue
        result = max(labels, key=lambda r: utc(r['recorded_at']))
        if (utc(result['actual_kickoff']) - timedelta(hours=decision_hours) < cutoff
                or utc(latest['recorded_at']) >= utc(result['actual_kickoff'])):
            exclusions['actual_kickoff_invalidates_cutoff'] += 1
            continue
        # One point per timestamp: choose latest recorded evidence, deduplicate redistributors.
        snapshots = {}
        for observation in sorted(observations, key=lambda p: utc(p['recorded_at'])):
            for s in observation['odds']:
                if (utc(s['at']) <= cutoff and utc(s['at']) < utc(result['actual_kickoff'])
                        and _eligible_source(s['source'], cutoff, max_age_hours)):
                    snapshots[utc(s['at'])] = s
        if not snapshots:
            exclusions['no_complete_odds_at_cutoff'] += 1
            continue
        ordered = sorted(snapshots.values(), key=lambda s: utc(s['at']))
        opening, current = ordered[0], ordered[-1]
        outcomes = latest['outcomes']; probabilities = current['fair_probabilities']
        baseline = max(outcomes, key=lambda o: (probabilities[o], o))
        movement = {o: 100 * (probabilities[o] - opening['fair_probabilities'][o]) for o in outcomes}
        gaps = {o: delta_pp(latest['shares'][o]) for o in outcomes}
        moving = max(outcomes, key=lambda o: (movement[o], o)) if len(ordered) > 1 else None
        moving = moving if moving and movement[moving] >= movement_threshold else None
        valid_gaps = {o: g for o, g in gaps.items() if g is not None}
        gap = max(valid_gaps, key=lambda o: (valid_gaps[o], o)) if valid_gaps else None
        gap = gap if gap and gaps[gap] >= gap_threshold else None
        combined = gap if gap == moving else None
        news = any(n['certainty'] == 'fact' and _eligible_source(n['source'], cutoff, max_age_hours)
                   for n in latest['news'])
        handles = {o: latest['shares'][o]['handle'] for o in outcomes}
        high = low = None
        if all(v is not None for v in handles.values()) and len(set(handles.values())) > 1:
            high = max(outcomes, key=lambda o: (handles[o], o))
            low = min(outcomes, key=lambda o: (handles[o], o))
        row = {'fixture': fixture_key(latest), 'market': latest['market'], 'line': latest['line'],
               'bookmaker': latest['bookmaker'], 'kickoff': latest['kickoff'],
               'decision_at': cutoff.isoformat(), 'odds_at': current['at'],
               'actual_kickoff': result['actual_kickoff'],
               'source_published_at': latest['source']['published_at'],
               'source_observed_at': latest['source']['observed_at'],
               'server_recorded_at': latest['recorded_at'],
               'result_recorded_at': result['recorded_at'],
               'prices': current['prices'], 'overround': current['overround'],
               'gaps_pp': gaps, 'movement_fair_pp': movement,
               'settlement': result['settlement'],
               'picks': dict(zip(RULES, (baseline, moving, gap, combined,
                                        combined if news else None, high, low)))}
        (test if partition == 'test' else development).append(row)
    test.sort(key=lambda r: (utc(r['kickoff']), r['fixture'], r['market'], r['line'], r['bookmaker']))
    development.sort(key=lambda r: (utc(r['kickoff']), r['fixture']))
    # Descriptive controls; do not pool different markets/books/price-margin-horizon bins blindly.
    strata = defaultdict(list)
    for r in test:
        price = r['prices'][r['picks']['baseline']]
        control = (r['market'], r['line'], r['bookmaker'], int(price * 2) / 2,
                   round(r['overround'], 2), decision_hours)
        strata[control].append(r)
    warnings = list(WARNINGS)
    if len({r['fixture'] for r in test}) < 100:
        warnings.append('Kis minta: 100-nál kevesebb független fixture; nincs igazolt előny.')
    if clock < end:
        warnings.append('A tesztidőszak még nem zárult le; az eredmény részleges.')
    if protocol is None:
        warnings.append('Feltáró történeti visszajátszás: nincs előre rögzített protokoll; nem igazolt érintetlen out-of-sample teszt.')
    else:
        warnings.append('Előre rögzített szabályok; az érintetlen adat és a teljes mintavételi manifest betartása emberi ellenőrzést igényel.')
    return {'mode': 'preregistered_chronological' if protocol else 'exploratory_chronological_replay',
            'test_period_complete': clock >= end,
            'protocol_hash': protocol_hash, 'development_n': len(development), 'test_n': len(test),
            'test_start': start.isoformat(), 'test_end_exclusive': end.isoformat(),
            'thresholds': {'gap_pp': gap_threshold, 'movement_fair_pp': movement_threshold},
            'development': {rule: _summary(development, rule) for rule in RULES},
            'test': {rule: _summary(test, rule) for rule in RULES},
            'controls': [{'market_line_book_odds_margin_horizon': list(k),
                          'summary': {rule: _summary(rows, rule) for rule in RULES}}
                         for k, rows in sorted(strata.items())],
            'rows': test, 'exclusions': dict(exclusions), 'warnings': warnings}
