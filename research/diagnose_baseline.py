"""Read saved chronological forecasts; never fit or change the prediction model."""
import argparse
from collections import defaultdict
import csv
import hashlib
import json
import math
from pathlib import Path
import random

TOP1_BINS = (0, .10, .15, .20, 1.0000001)
FAVORITE_BINS = (0, .40, .50, .60, .70, .80, 1.0000001)
SCORES = ((0,0), (1,1), (1,0), (0,1), (2,2))


def poisson(lam):
    if not math.isfinite(lam) or not 0 < lam <= 20:
        raise ValueError('Invalid saved lambda')
    values = [math.exp(-lam)]
    for i in range(1,101):
        values.append(values[-1]*lam/i)
    return values


def enrich(row):
    h, a = int(row['actual_home']), int(row['actual_away'])
    lh, la = float(row['lambda_home']), float(row['lambda_away'])
    ph, pa = poisson(lh), poisson(la)
    probs = [0., 0., 0.]
    for i,p in enumerate(ph):
        for j,q in enumerate(pa):
            probs[0 if i>j else 1 if i==j else 2] += p*q
    mass = sum(probs)
    probs = [p/mass for p in probs]
    th,ta = int(row['top1_home']),int(row['top1_away'])
    top_prob = float(row['top1_probability'])
    hit = int((h,a)==(th,ta))
    if hit != int(row['top1_hit']) or not math.isclose(top_prob,ph[th]*pa[ta],rel_tol=1e-10):
        raise ValueError('Inconsistent saved forecast')
    favorite = max(range(3),key=lambda i:probs[i])
    actual = 0 if h>a else 1 if h==a else 2
    out = {'season':row['season'],'date':row['date'],'split':row['split'],
           'expected_home':lh,'actual_home':h,'expected_away':la,'actual_away':a,
           'expected_total':lh+la,'actual_total':h+a,
           'home_bias':h-lh,'away_bias':a-la,'total_bias':h+a-lh-la,
           'draw_expected':probs[1],'draw_actual':int(h==a),
           'draw_bias':int(h==a)-probs[1],
           'top1_expected':top_prob,'top1_actual':hit,'top1_bias':hit-top_prob,
           'favorite_expected':probs[favorite],'favorite_actual':int(actual==favorite),
           'favorite_bias':int(actual==favorite)-probs[favorite]}
    for x,y in SCORES:
        label=f'{x}-{y}'
        out[label+'_expected']=ph[x]*pa[y]
        out[label+'_actual']=int((h,a)==(x,y))
        out[label+'_bias']=out[label+'_actual']-out[label+'_expected']
    return out


def residual_intervals(rows, keys, samples=2000):
    """Paired residual means; resample season/date clusters, seed=42."""
    groups = defaultdict(list)
    for row in rows:
        groups[(row['season'],row['date'])].append(row)
    groups = [v for _,v in sorted(groups.items())]
    if not groups:
        return {key:None for key in keys}
    counts = [len(g) for g in groups]
    sums = [[sum(r[k] for r in g) for k in keys] for g in groups]
    values = [[] for _ in keys]
    rng = random.Random(42)
    for _ in range(samples):
        indices = [rng.randrange(len(groups)) for _ in groups]
        n = sum(counts[i] for i in indices)
        for j in range(len(keys)):
            values[j].append(sum(sums[i][j] for i in indices)/n)
    for v in values:v.sort()
    return {key:[v[int(.025*samples)],v[int(.975*samples)]] for key,v in zip(keys,values)}


def summary(rows, intervals=True):
    if not rows:return {'n':0}
    keys=[k for k in rows[0] if k not in ('season','date','split')]
    out={'n':len(rows),'means':{k:sum(r[k] for r in rows)/len(rows) for k in keys},
         'counts':{k:sum(r[k] for r in rows) for k in keys if k.endswith('_actual')}}
    if intervals:
        out['residual_day_bootstrap95']=residual_intervals(rows,[k for k in keys if k.endswith('_bias')])
    return out


def wilson(hits, n):
    z=1.959963984540054
    den=1+z*z/n
    center=(hits/n+z*z/(2*n))/den
    radius=z*math.sqrt((hits/n)*(1-hits/n)/n+z*z/(4*n*n))/den
    return [max(0.,center-radius),min(1.,center+radius)]


def calibration(rows, prefix, boundaries):
    result=[]
    for low,high in zip(boundaries,boundaries[1:]):
        subset=[r for r in rows if low <= r[prefix+'_expected'] < high]
        if not subset:
            result.append({'lower':low,'upper':min(high,1),'n':0});continue
        n=len(subset)
        expected=sum(r[prefix+'_expected'] for r in subset)/n
        actual=sum(r[prefix+'_actual'] for r in subset)/n
        hits=sum(r[prefix+'_actual'] for r in subset)
        clusters=len({(r['season'],r['date']) for r in subset})
        limited=n<50 or clusters<20 or hits in (0,n)
        result.append({'lower':low,'upper':min(high,1),'n':n,
                       'limited_sample':limited,'observed_wilson95':wilson(hits,n),
                       'expected':expected,'actual':actual,'hits':sum(r[prefix+'_actual'] for r in subset),
                       'actual_minus_expected':actual-expected,
                       'residual_day_bootstrap95':None if limited else residual_intervals(subset,[prefix+'_bias'])[prefix+'_bias']})
    return result


def diagnose(path):
    raw=path.read_bytes()
    with path.open(encoding='utf-8-sig',newline='') as f:
        saved=[r for r in csv.DictReader(f) if r['model']=='baseline']
    ids=[(r['season'],r['match_id']) for r in saved]
    if len(ids)!=len(set(ids)):raise ValueError('Duplicate baseline forecasts')
    rows=[enrich(r) for r in saved]
    scopes={name:[r for r in rows if name=='all_eligible' or r['split']=='test']
            for name in ('all_eligible','original_test_blocks')}
    return {'input_sha256':hashlib.sha256(raw).hexdigest(),'model':'unchanged_baseline',
            'status':'Post-hoc diagnostics of previously seen final-results replays; no fitting.',
            'scopes':{name:{'summary':summary(subset),
                            'top1_calibration':calibration(subset,'top1',TOP1_BINS),
                            'favorite_1x2_calibration':calibration(subset,'favorite',FAVORITE_BINS)}
                      for name,subset in scopes.items()},
            'per_season':{season:summary([r for r in rows if r['season']==season],False)
                          for season in sorted({r['season'] for r in rows})}}


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('predictions_csv',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    args.output.write_text(json.dumps(diagnose(args.predictions_csv),indent=2)+'\n')
