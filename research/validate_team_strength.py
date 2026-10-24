"""Frozen-config evaluation of PR #4; run with the PR source on PYTHONPATH."""
from concurrent.futures import ProcessPoolExecutor, as_completed
from collections import Counter, defaultdict
from pathlib import Path
from dataclasses import asdict
import csv
import argparse
import hashlib
import json
import random
from time import perf_counter

from correct_score_backtest import read_csv, backtest, aggregate
from team_strength import Config

BASE = Path.cwd()
DATA = BASE / 'multiseason_data'
OUT = BASE / 'strength_validation_results'
SEASONS = [('2021','2020/21'),('2122','2021/22'),('2223','2022/23'),
           ('2324','2023/24'),('2425','2024/25')]
MODELS = ['baseline','freshness','core']
COMMIT = '90031b60a17329560deef0f94078d6df6ba9645e'


def run_one(item):
    code, season, data_dir, output_dir = item
    data_dir, output_dir = Path(data_dir), Path(output_dir)
    data = data_dir/f'E0_{code}.csv'
    matches = read_csv(data, season=season)
    counts = Counter(t for m in matches for t in (m.home_id,m.away_id))
    assert len(matches)==380, (season,len(matches))
    assert len({m.match_id for m in matches})==380
    assert len(counts)==20 and set(counts.values())=={38}
    assert min(m.match_date.year for m in matches)==int(season[:4])
    assert max(m.match_date.year for m in matches)==int(season[:4])+1
    report = backtest(matches, Config(mode='core'))
    assert report['evaluated']+sum(report['skipped'].values())==380
    report['source_file_sha256'] = hashlib.sha256(data.read_bytes()).hexdigest()
    report['model_commit'] = COMMIT
    report['season'] = season
    report['data_validation']={'matches':380,'unique_teams':20,'matches_per_team':38}
    (output_dir/f'backtest_{code}.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    return report


def stratified_nll_interval(reports, samples=2000):
    strata=[]
    for r in reports:
        groups=defaultdict(list)
        for row in r['rows']:
            if row['split']=='test':
                groups[row['date']].append(row['metrics']['core']['nll']-row['metrics']['baseline']['nll'])
        strata.append([(sum(v),len(v)) for _,v in sorted(groups.items())])
    rng=random.Random(42)
    values=[]
    for _ in range(samples):
        total=0.;n=0
        for days in strata:
            for _ in days:
                s,k=days[rng.randrange(len(days))]
                total+=s;n+=k
        values.append(total/n)
    values.sort()
    return [values[int(.025*samples)],values[int(.975*samples)]]


def main():
    OUT.mkdir(exist_ok=True)
    started=perf_counter()
    reports=[]
    with ProcessPoolExecutor(max_workers=2) as pool:
        futures={pool.submit(run_one,(*s,str(DATA),str(OUT))):s for s in SEASONS}
        for future in as_completed(futures):
            r=future.result();reports.append(r)
            print(json.dumps({'season':r['season'],'evaluated':r['evaluated'],
                              'test_matches':r['summary']['test']['core']['matches'],
                              'runtime':r['runtime_seconds']},ensure_ascii=False),flush=True)
    reports.sort(key=lambda r:r['season'])
    allrows=[]
    for r in reports:
        for row in r['rows']:
            allrows.append({**row,'season':r['season'],'date':r['season']+':'+row['date']})
    testrows=[r for r in allrows if r['split']=='test']
    pooled=aggregate(testrows,MODELS)
    complete=aggregate(allrows,MODELS)
    core,base=pooled['core'],pooled['baseline']
    ci=core['paired_nll_difference95']
    recommend=core['matches']>=200 and ci[1]<0 and core['brier']<=base['brier']
    result={'model_commit':COMMIT,'plan_sha256':'fb98b8f14a76bb145f2ee41cffbd0143e145fa02753f27382b85487df795b1ed',
            'config':asdict(Config(mode='core')),
            'seasons':[r['season'] for r in reports],
            'total_matches':sum(r['total'] for r in reports),
            'evaluated':len(allrows),'test_matches':len(testrows),
            'pooled_test':pooled,'secondary_all_eligible':complete,
            'stratified_day_bootstrap_nll95':stratified_nll_interval(reports),
            'nll_difference':core['nll']-base['nll'],'brier_difference':core['brier']-base['brier'],
            'research_activation_rule_passed':recommend,'default_model':'baseline',
            'per_season':[{k:v for k,v in r.items() if k!='rows'} for r in reports],
            'runtime_seconds':perf_counter()-started}
    for key,rows in [('test_hits',testrows),('all_eligible_hits',allrows)]:
        result[key]={model:{metric:sum(row['metrics'][model][metric] for row in rows)
                           for metric in ['top1','top5']} for model in MODELS}
    (OUT/'summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    with (OUT/'predictions.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.writer(f)
        w.writerow(['season','date','split','match_id','home','away','actual_home','actual_away',
                    'model','lambda_home','lambda_away','top1_home','top1_away','top1_probability',
                    'top1_hit','top5_hit','NLL','Brier','fallback'])
        identities={m.match_id:(m.home_id,m.away_id) for code,season in SEASONS
                    for m in read_csv(DATA/f'E0_{code}.csv',season=season)}
        for row in allrows:
            for model in MODELS:
                p=row['forecasts'][model];m=row['metrics'][model];o=p['candidate']
                w.writerow([row['season'],row['date'].split(':',1)[1],row['split'],row['match_id'],
                            *identities[row['match_id']],*row['label'],model,*o['lambdas'],
                            *o['top5'][0],m['top1'],m['top5'],m['nll'],m['brier'],p['fallback_reason']])
    print(json.dumps({k:result[k] for k in ['evaluated','test_matches','test_hits','pooled_test',
                     'stratified_day_bootstrap_nll95','research_activation_rule_passed']},indent=2),flush=True)


if __name__=='__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    DATA = args.data_dir.resolve()
    OUT = args.output_dir.resolve()
    main()
