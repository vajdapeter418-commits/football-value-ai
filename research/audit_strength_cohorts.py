"""Descriptive diagnostics after the frozen five-season test; never tunes a model."""
import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
from correct_score_backtest import read_csv, aggregate
from team_strength import Config

SEASONS = [('2021','2020/21'),('2122','2021/22'),('2223','2022/23'),
           ('2324','2023/24'),('2425','2024/25')]
MODELS = ['baseline','core']

def audit(data_dir, result_dir):
    summary = json.loads((result_dir/'summary.json').read_text())
    cohorts = {'first_100_fixtures':[], 'venue_history_3_to_5':[]}
    seasons = []
    for code, season in SEASONS:
        raw = data_dir/f'E0_{code}.csv'
        report = json.loads((result_dir/f'backtest_{code}.json').read_text())
        assert hashlib.sha256(raw.read_bytes()).hexdigest() == report['source_file_sha256']
        fixtures = sorted(read_csv(raw, season=season), key=lambda m:(m.match_date,m.match_id))
        first_ids = {m.match_id for m in fixtures[:100]}
        rows = report['rows']
        early = [r for r in rows if r['match_id'] in first_ids]
        sparse = [r for r in rows if min(r['forecasts']['core']['raw_counts'][1:]) <= 5]
        assert all(min(r['forecasts']['core']['raw_counts'][1:]) >= 3 for r in sparse)
        for r in rows:
            assert all(.75 <= ratio <= 1.25 for ratio in r['forecasts']['core']['applied_ratios'])
            assert r['forecasts']['baseline']['candidate'] == r['forecasts']['core']['baseline']
        for name, subset in [('first_100_fixtures',early),('venue_history_3_to_5',sparse)]:
            cohorts[name].extend({**r,'date':season+':'+r['date']} for r in subset)
        seasons.append({'season':season,'sha256':report['source_file_sha256'],
                        'evaluated':len(rows),'skipped':report['skipped'],
                        'first_100_evaluated':len(early),'first_100_skipped':100-len(early),
                        'sparse_evaluated':len(sparse),
                        'test':{k:report['summary']['test'][k] for k in MODELS},
                        'core_fallbacks':sum(v for k,v in report['fallbacks'].items() if k.startswith('core:')),
                        'core_clipped':sum(any(r['forecasts']['core']['clipped']) for r in rows)})
    return {'model_commit':summary['model_commit'],'config':asdict(Config(mode='core')),
            'policy':'historical_results_replay','total_matches':summary['total_matches'],
            'evaluated':summary['evaluated'],'primary_test_matches':summary['test_matches'],
            'primary_test':{k:summary['pooled_test'][k] for k in MODELS},
            'primary_test_hits':{k:summary['test_hits'][k] for k in MODELS},
            'paired_nll_difference95':summary['pooled_test']['core']['paired_nll_difference95'],
            'activation_recommended':summary['research_activation_rule_passed'],
            'cohort_status':'Post-hoc descriptive diagnostics; overlapping subsets; not new untouched tests.',
            'cohorts':{k:aggregate(v,MODELS) for k,v in cohorts.items()},'seasons':seasons}

if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--data-dir',type=Path,required=True)
    parser.add_argument('--result-dir',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    args.output.write_text(json.dumps(audit(args.data_dir,args.result_dir),ensure_ascii=False,indent=2)+'\n')
