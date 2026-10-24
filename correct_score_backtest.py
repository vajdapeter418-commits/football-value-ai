"""Paired expanding-window retrospective evaluation, also executable without UI."""
import argparse
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, replace
from datetime import datetime, time, timedelta, timezone
import csv
import json
import math
from pathlib import Path
import random
from time import perf_counter

from asof_features import (REPLAY, STRICT, Match, Request, adapt_tuples, snapshot,
                           features, digest, utc)
from team_strength import Config, TrainingExample, predict, train_extra


def read_csv(path, league='E0', season='selected'):
    with open(path, encoding='utf-8-sig',newline='') as stream:
        reader = csv.DictReader(stream)
        if not {'Div','Date','HomeTeam','AwayTeam','FTHG','FTAG'}.issubset(reader.fieldnames or ()):
            raise ValueError('Missing CSV columns')
        rows = []
        for r in reader:
            if r['Div'] != league or not r['FTHG'] or not r['FTAG']:
                continue
            if r.get('Status','completed').lower() not in ('completed','ft'):
                continue
            if r.get('Period','regulation').lower() not in ('regulation','90'):
                continue
            d = datetime.strptime(r['Date'],'%d/%m/%Y').date()
            rows.append((r['HomeTeam'],r['AwayTeam'],int(r['FTHG']),int(r['FTAG']),d))
    return adapt_tuples(rows,league,season)


def nll(lambdas, label):
    return sum(lam-y*math.log(lam)+math.lgamma(y+1) for lam,y in zip(lambdas,label))


def metrics(outcome, label):
    top = outcome.top5
    y = 0 if label[0]>label[1] else 1 if label[0]==label[1] else 2
    return {'top1':int(label==top[0][:2]),'top5':int(label in [r[:2] for r in top]),
            'estimated_top1':top[0][2],'estimated_top5':sum(r[2] for r in top),
            'nll':nll(outcome.lambdas,label),
            'brier':sum((p-int(i==y))**2 for i,p in enumerate(outcome.one_x_two))}


def wilson(hits,n):
    if not n:
        return None
    z = 1.959963984540054
    p = hits/n
    den = 1+z*z/n
    center = (p+z*z/(2*n))/den
    radius = z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/den
    return max(0,center-radius),min(1,center+radius)


def paired_bootstrap(rows,model='core',samples=2000):
    groups = defaultdict(list)
    for r in rows:
        groups[r['date']].append(r['metrics'][model]['nll']-r['metrics']['baseline']['nll'])
    days = sorted(groups)
    if not days:
        return None
    rng = random.Random(42)
    values = []
    sums = [sum(groups[d]) for d in days]
    counts = [len(groups[d]) for d in days]
    for _ in range(samples):
        indices = [rng.randrange(len(days)) for _ in days]
        values.append(sum(sums[i] for i in indices)/sum(counts[i] for i in indices))
    values.sort()
    return values[int(.025*samples)],values[min(samples-1,int(.975*samples))]


def boundaries(matches):
    days = sorted({m.match_date for m in matches})
    i,j = int(len(days)*.6),int(len(days)*.8)
    return {'development':tuple(days[:i]),'validation':tuple(days[i:j]),'test':tuple(days[j:])}


def aggregate(rows, models):
    out = {}
    for model in models:
        vals = [r['metrics'][model] for r in rows]
        result = {'matches':len(vals)}
        if vals:
            result.update({k:sum(v[k] for v in vals)/len(vals) for k in vals[0]})
            result['top1_wilson95'] = wilson(sum(v['top1'] for v in vals),len(vals))
            result['top5_wilson95'] = wilson(sum(v['top5'] for v in vals),len(vals))
            result['paired_nll_difference95'] = paired_bootstrap(rows,model)
        out[model] = result
    return out


def backtest(matches, config=Config(mode='core'), extras=(), policy=REPLAY,
             historical_matches=None):
    started = perf_counter()
    matches = tuple(matches)
    extras = tuple(extras)
    if policy == STRICT and historical_matches is None:
        raise ValueError('Strict evaluation requires separate historical_matches archive')
    history = tuple(historical_matches) if historical_matches is not None else matches
    if len({(m.league,m.season) for m in matches}) > 1:
        raise ValueError('Evaluate one league/season at a time')
    # Input validation independent of chronology. Retrospective labels are a separate
    # evaluator dataset, never inserted into a prediction feature object.
    unique = {}
    for m in matches:
        if m.match_id in unique and unique[m.match_id] != m:
            raise ValueError('Conflicting evaluator labels; supply one settled label per ID')
        unique[m.match_id] = m
    matches = tuple(sorted(unique.values(),key=lambda m:(m.match_date,m.match_id)))
    split = boundaries(matches)  # fixed before any measurement
    membership = {d:k for k,days in split.items() for d in days}
    configs = {'baseline':replace(config,mode='baseline',blocks=()),
               'freshness':replace(config,mode='freshness',blocks=()),
               'core':replace(config,mode='core',blocks=())}
    for block in ('xg','set_piece','style','players'):
        configs['core+'+block] = replace(config,mode='extras',blocks=(block,))
    configs['full'] = replace(config,mode='extras')
    examples = {k:[] for k in configs}
    historical_examples = {k:[] for k in configs}
    skipped,fallbacks,coverage = Counter(),Counter(),Counter()
    rows = []
    # No fitted state is updated by a current day's labels before its forecasts.
    for day in sorted({m.match_date for m in matches}):
        pending = []
        for target in (m for m in matches if m.match_date==day):
            if not target.completed or not target.regulation:
                skipped['not_completed_regulation'] += 1
                continue
            if policy == STRICT and target.kickoff_utc is None:
                skipped['missing_target_kickoff'] += 1
                continue
            cutoff = (target.kickoff_utc if policy==STRICT else
                      datetime.combine(day,time.min,tzinfo=timezone.utc))
            req = Request(target.home_id,target.away_id,target.league,target.season,
                          day,cutoff,policy,target.kickoff_utc)
            snap = snapshot(history,req,extras)
            if policy == STRICT:
                known_results = {m.match_id:m for m in snap.matches}
                for name in configs:
                    examples[name] = []
                    for match_id, example in historical_examples[name]:
                        result = known_results.get(match_id)
                        if result is not None:
                            ev = result.evidence
                            examples[name].append(replace(example,
                                label=(result.home_goals,result.away_goals),
                                label_known_at=max(ev.effective_at,ev.published_at,
                                                   ev.captured_at,result.completed_at)))
            nh = sum(m.home_id==target.home_id for m in snap.matches)
            na = sum(m.away_id==target.away_id for m in snap.matches)
            if len(snap.matches)<60 or min(nh,na)<3:
                skipped['insufficient_history_60_3_3'] += 1
                continue
            forecasts = {}
            for name,cfg in configs.items():
                model = train_extra(examples[name],cutoff,cfg) if cfg.mode=='extras' else None
                try:
                    forecasts[name] = predict(snap,req.home,req.away,cfg,model)
                except ValueError as e:
                    if name == 'baseline':
                        skipped['baseline:'+str(e)] += 1
                        break
                    # Shared baseline failure has already been handled; unexpected
                    # candidate input errors are counted instead of dropping its row.
                    forecasts[name] = replace(forecasts['baseline'],fallback_reason=str(e))
                f = forecasts[name]
                if f.fallback_reason:
                    fallbacks[name+':'+f.fallback_reason] += 1
                for b in f.active_signals:
                    coverage[name+':'+b] += 1
                if cfg.mode=='extras':
                    try:
                        fh,fa = features(snap,cfg.blocks,cfg.half_life)
                    except ValueError:
                        # Invalid provider contracts already trigger a visible prediction fallback.
                        continue
                    # Store only forecast-time features. Strict labels are resolved
                    # from the archive anew at each subsequent prediction cutoff.
                    known = datetime.combine(day+timedelta(days=1),time.min,tzinfo=timezone.utc)
                    example = TrainingExample(cutoff,known,f.core_lambdas,
                        tuple(sorted(fh.items())),tuple(sorted(fa.items())),
                        (0,0) if policy == STRICT else (target.home_goals,target.away_goals))
                    pending.append((name,target.match_id,example))
            if len(forecasts)!=len(configs):
                continue
            label = (target.home_goals,target.away_goals)
            rows.append({'match_id':target.match_id,'date':str(day),'split':membership[day],
                         'forecasts':{k:asdict(v) for k,v in forecasts.items()},
                         'label':label,'metrics':{k:metrics(v.candidate,label) for k,v in forecasts.items()}})
        for name,match_id,example in pending:
            if policy == STRICT:
                historical_examples[name].append((match_id,example))
            else:
                examples[name].append(example)
    summary = {k:aggregate([r for r in rows if r['split']==k],configs) for k in split}
    test = summary['test']
    candidate_name = 'full' if config.blocks else 'core'
    cand,base = test[candidate_name],test['baseline']
    interval = cand.get('paired_nll_difference95')
    sufficient = cand['matches']>=200 and (not config.blocks or any(
        r['forecasts'][candidate_name]['extra_model_hash'] for r in rows if r['split']=='test'))
    activation = bool(sufficient and interval and interval[1]<0 and cand['brier']<=base['brier'])
    return {'policy':policy,
            'description':('Retrospektív eredmény-visszateszt; a statikus forrás utólagos javításait nem zárja ki.'
                           if policy==REPLAY else 'Strict as-of: archivált publikálási és rögzítési bizonyíték szükséges.'),
            'input_hash':digest([asdict(m) for m in matches]),
            'history_hash':digest([asdict(m) for m in history]),'extras_hash':digest([asdict(x) for x in extras]),
            'config':asdict(config),'config_hash':digest(asdict(config)),
            'split_dates':{k:([str(v[0]),str(v[-1])] if v else []) for k,v in split.items()},
            'summary':summary,'evaluated':len(rows),'skipped':dict(skipped),
            'total':len(matches),'fallbacks':dict(fallbacks),'feature_coverage':dict(coverage),
            'evidence':'sufficient' if sufficient else 'insufficient',
            'activation_recommended':activation,'default_model':'baseline',
            'extras_status':'No real extra provider or archive configured; fixture tests are not integration evidence.'
                            if not extras else 'Supplied versioned archive; see feature coverage and training threshold.',
            'runtime_seconds':perf_counter()-started,'rows':rows}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('csv',type=Path)
    p.add_argument('--season',required=True)
    p.add_argument('--league',default='E0')
    p.add_argument('--output',type=Path,default=Path('backtest-report.json'))
    args = p.parse_args()
    report = backtest(read_csv(args.csv,args.league,args.season))
    report['input_bytes'] = args.csv.stat().st_size
    import hashlib
    report['input_file_sha256'] = hashlib.sha256(args.csv.read_bytes()).hexdigest()
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='rows'},ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()

