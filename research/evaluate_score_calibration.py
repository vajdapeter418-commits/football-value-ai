"""Frozen, chronological calibration experiment on already-seen replay forecasts."""
import argparse
from dataclasses import asdict, replace
import csv
from datetime import date
import hashlib
import json
from pathlib import Path
from correct_score_backtest import paired_bootstrap
from score_calibration import Example, fit, apply
from team_strength import outcome

EXPECTED_HASH='9a565df75e791b90ea6356cec1a15507de546554176dca402fb882748a03f486'


def baseline(row):
    result = {key:float(row[field]) for key,field in
            [('nll','NLL'),('brier','Brier'),('top1','top1_hit'),('top5','top5_hit'),
             ('estimated_top1','top1_probability')]}
    result['estimated_top5']=sum(x[2] for x in outcome((float(row['lambda_home']),float(row['lambda_away']))).top5)
    return result


def score(row, artifact):
    lambdas=(float(row['lambda_home']),float(row['lambda_away']))
    label=(int(row['actual_home']),int(row['actual_away']))
    q=apply(lambdas,artifact,date.fromisoformat(row['date']))
    y=0 if label[0]>label[1] else 1 if label[0]==label[1] else 2
    result={'nll':q.nll(label),'brier':sum((p-int(i==y))**2 for i,p in enumerate(q.one_x_two)),
            'top1':int(label==q.top5[0][:2]),'top5':int(label in [x[:2] for x in q.top5]),
            'estimated_top1':q.top5[0][2],'estimated_top5':sum(x[2] for x in q.top5)}
    assert result['top1']==int(row['top1_hit']) and result['top5']==int(row['top5_hit'])
    if artifact.temperature==1.:result.update(baseline(row))
    return result


def mean(rows):
    if not rows:return {'n':0}
    return {'n':len(rows),**{k:sum(r[k] for r in rows)/len(rows) for k in rows[0]}}


def evaluate(path):
    raw=path.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=EXPECTED_HASH:
        raise ValueError('Input differs from frozen experiment')
    with path.open(encoding='utf-8-sig',newline='') as f:
        rows=[r for r in csv.DictReader(f) if r['model']=='baseline']
    reports=[];pooled=[]
    for season in sorted({r['season'] for r in rows}):
        parts={part:sorted([r for r in rows if r['season']==season and r['split']==part],
                           key=lambda r:(r['date'],r['match_id']))
               for part in ('development','validation','test')}
        dev,val,test=(parts[k] for k in ('development','validation','test'))
        assert max(r['date'] for r in dev)<min(r['date'] for r in val)
        assert max(r['date'] for r in val)<min(r['date'] for r in test)
        examples=[Example(date.fromisoformat(r['date']),
                          (float(r['lambda_home']),float(r['lambda_away'])),
                          (int(r['actual_home']),int(r['actual_away']))) for r in dev]
        artifact=fit(examples,date.fromisoformat(val[0]['date']))
        val_base=mean([baseline(r) for r in val]);val_candidate=mean([score(r,artifact) for r in val])
        accepted=(val_candidate['nll'] < val_base['nll']-1e-12
                  and val_candidate['brier'] <= val_base['brier']+1e-12)
        selected=replace(artifact,temperature=artifact.temperature if accepted else 1.,
                         reason='validation_accepted' if accepted else 'validation_rejected_identity',
                         selection_through=date.fromisoformat(val[-1]['date']))
        b=[];c=[];s=[]
        for row in test:
            b.append(baseline(row));c.append(score(row,artifact));s.append(score(row,selected))
            pooled.append({'date':season+':'+row['date'],
                           'metrics':{'baseline':b[-1],'candidate':c[-1],'selected':s[-1]}})
        reports.append({'season':season,'fit':asdict(artifact),'selected':asdict(selected),
                        'validation':{'baseline':val_base,'candidate':val_candidate},
                        'test':{'baseline':mean(b),'candidate':mean(c),'selected':mean(s)}})
    final={name:mean([r['metrics'][name] for r in pooled])
           for name in ('baseline','candidate','selected')}
    return {'protocol':'TEMPERATURE_EXPERIMENT_PLAN.md','input_sha256':EXPECTED_HASH,
            'status':'Exploratory on previously seen historical_results_replay data; no activation.',
            'per_season':reports,'pooled_original_test_blocks':final,
            'selected_minus_baseline_nll95':paired_bootstrap(pooled,'selected'),
            'candidate_minus_baseline_nll95':paired_bootstrap(pooled,'candidate'),
            'default_model':'baseline','activation_recommended':False}


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('predictions_csv',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    args.output.write_text(json.dumps(evaluate(args.predictions_csv),default=str,indent=2)+'\n')
