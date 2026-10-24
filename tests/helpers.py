from datetime import date, datetime, timedelta, timezone
from dataclasses import replace
from asof_features import Request, Evidence, adapt_tuples, snapshot


def league(days=100):
    teams = ('A','B','C','D')
    return adapt_tuples([(teams[(i+j)%4],teams[(i+j+1)%4],(i+j)%4,(i+2*j)%3,
                          date(2025,1,1)+timedelta(days=i))
                         for i in range(days) for j in (0,2)])


def request(day=date(2025,4,11), policy='historical_results_replay', home='A', away='B'):
    return Request(home,away,'E0','selected',day,datetime.combine(day,datetime.min.time(),timezone.utc),policy)


def evidence(t=None,version=1,source='fixture',units='xG/match',record='test'):
    t=t or datetime(2024,12,31,tzinfo=timezone.utc)
    return Evidence(source,record,t,t,t,version,units,'source_checked','fixture-hash')
