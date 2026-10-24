"""Manual, append-only provider observations. This module never changes model lambdas."""
import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, build_opener, HTTPRedirectHandler

FPL = 'https://fantasy.premierleague.com/api/'
API_FOOTBALL = 'https://v3.football.api-sports.io/'
MAX_BYTES = 12 * 1024 * 1024


def now():
    return datetime.now(timezone.utc)


def stamp(value):
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError('Timezone-aware UTC-compatible timestamp required')
    return value.astimezone(timezone.utc).isoformat(timespec='microseconds')


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args):
        # Never forward a credential to a redirect destination.
        return None


@dataclass(frozen=True)
class Observation:
    endpoint: str
    body: bytes
    fetched_at: datetime


def fetch(endpoint, *, api_key=None):
    allowed = (endpoint in (FPL+'bootstrap-static/', FPL+'fixtures/',
                           API_FOOTBALL+'fixtures?league=39&season=2024&date=2024-08-16') or
               re.fullmatch(re.escape(API_FOOTBALL)+r'(?:fixtures/statistics|fixtures/lineups|injuries)\?fixture=[1-9][0-9]{0,11}',endpoint) is not None or
               endpoint.startswith(API_FOOTBALL+'leagues?'))
    if not allowed:
        raise ValueError('Unapproved provider endpoint')
    headers = {'User-Agent': 'FootballValueAI/1.0'}
    if endpoint.startswith(API_FOOTBALL):
        if not api_key:
            raise ValueError('API_FOOTBALL_KEY is not configured')
        headers['x-apisports-key'] = api_key
    try:
        with build_opener(NoRedirect).open(Request(endpoint, headers=headers), timeout=25) as response:
            if response.status != 200:
                raise ValueError('Provider did not return HTTP 200')
            body = response.read(MAX_BYTES+1)
            fetched_at = now()
    except HTTPError as error:
        raise ValueError(f'Provider HTTP {error.code}; no response body logged') from None
    except (URLError, TimeoutError, OSError):
        raise ValueError('Provider connection failed; no credentials or response body logged') from None
    if len(body)>MAX_BYTES:
        raise ValueError('Provider response too large')
    json.loads(body)
    return Observation(endpoint, body, fetched_at)


def validate_fpl(observations, season):
    if not re.fullmatch(r'20\d\d/\d\d', season):
        raise ValueError('Season format must be YYYY/YY')
    year=int(season[:4])
    if season[-2:] != str(year+1)[-2:]:
        raise ValueError('Season must cover consecutive years')
    if {x.endpoint for x in observations} != {FPL+'bootstrap-static/', FPL+'fixtures/'} or len(observations)!=2:
        raise ValueError('Both FPL endpoints are required exactly once')
    data={x.endpoint:json.loads(x.body) for x in observations}
    boot,fixtures=data[FPL+'bootstrap-static/'],data[FPL+'fixtures/']
    if (not isinstance(boot,dict) or not isinstance(boot.get('teams'),list)
            or not isinstance(boot.get('elements'),list) or not isinstance(fixtures,list)
            or not boot['teams'] or not boot['elements'] or not fixtures):
        raise ValueError('Missing FPL teams, players or fixtures')
    ids=[t.get('id') for t in boot['teams']]
    if any(type(i) is not int for i in ids) or len(set(ids))!=len(ids):
        raise ValueError('Invalid/duplicate FPL team IDs')
    player_ids=[p.get('id') for p in boot['elements']]
    if (any(type(i) is not int for i in player_ids) or len(set(player_ids))!=len(player_ids)
            or any(p.get('team') not in ids for p in boot['elements'])):
        raise ValueError('Invalid FPL player identity/team')
    fixture_ids=[]
    dated=0
    for fixture in fixtures:
        fixture_ids.append(fixture.get('id'))
        if (fixture.get('team_h') not in ids or fixture.get('team_a') not in ids
                or fixture.get('team_h')==fixture.get('team_a')):
            raise ValueError('Fixture/team identity mismatch')
        if fixture.get('kickoff_time'):
            kickoff=datetime.fromisoformat(fixture['kickoff_time'].replace('Z','+00:00'))
            stamp(kickoff)
            if not (datetime(year,7,1,tzinfo=timezone.utc)<=kickoff<datetime(year+1,7,1,tzinfo=timezone.utc)):
                raise ValueError('FPL feed does not match the requested season')
            dated+=1
    if (not dated or any(type(i) is not int for i in fixture_ids)
            or len(set(fixture_ids))!=len(fixture_ids)):
        raise ValueError('Missing/duplicate fixture identities or dated fixtures')
    return {'teams':len(ids),'players':len(player_ids),'fixtures':len(fixtures)}


def validate_coverage(observation, league, year):
    data=json.loads(observation.body)
    if (not isinstance(data,dict) or data.get('errors') or not isinstance(data.get('response'),list)
            or data.get('results')!=len(data['response'])):
        raise ValueError('API-FOOTBALL error or invalid envelope; no body logged')
    paging=data.get('paging',{})
    if paging.get('total',1)>1:
        raise ValueError('Incomplete paginated coverage response')
    matches=[r for r in data['response'] if r.get('league',{}).get('id')==league]
    seasons=[s for r in matches for s in r.get('seasons',[]) if s.get('year')==year]
    if len(seasons)!=1:
        raise ValueError('Requested league-season is not covered by this response')
    return seasons[0].get('coverage',{})


class Archive:
    def __init__(self,path):
        path=Path(path)
        path.parent.mkdir(parents=True,exist_ok=True)
        self.db=sqlite3.connect(path)
        self.db.execute('PRAGMA foreign_keys=ON')
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS provider_bundles(
                id INTEGER PRIMARY KEY, provider TEXT NOT NULL, scope TEXT NOT NULL,
                stored_at TEXT NOT NULL, available_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS provider_observations(
                bundle_id INTEGER NOT NULL REFERENCES provider_bundles(id),
                endpoint TEXT NOT NULL, fetched_at TEXT NOT NULL,
                published_at TEXT, sha256 TEXT NOT NULL, body BLOB NOT NULL,
                PRIMARY KEY(bundle_id,endpoint));
        ''')

    def close(self):
        self.db.close()

    def save(self,provider,scope,observations):
        observations=tuple(observations)
        if not observations or len({o.endpoint for o in observations})!=len(observations):
            raise ValueError('Empty or duplicate observation bundle')
        stored=now()
        for o in observations:
            stamp(o.fetched_at)
            if o.fetched_at>stored:
                raise ValueError('Future fetch time')
            json.loads(o.body)
        # Retrospective imports cannot claim availability at their old fetch time.
        available=max(stored,*(o.fetched_at for o in observations))
        with self.db:
            cursor=self.db.execute('INSERT INTO provider_bundles(provider,scope,stored_at,available_at) VALUES(?,?,?,?)',
                                   (provider,scope,stamp(stored),stamp(available)))
            bundle=cursor.lastrowid
            for o in observations:
                self.db.execute('INSERT INTO provider_observations VALUES(?,?,?,?,?,?)',
                                (bundle,o.endpoint,stamp(o.fetched_at),None,
                                 hashlib.sha256(o.body).hexdigest(),o.body))
        return bundle

    def latest(self,provider,scope,cutoff):
        row=self.db.execute('SELECT id,available_at FROM provider_bundles '
                            'WHERE provider=? AND scope=? AND available_at<? '
                            'ORDER BY available_at DESC,id DESC LIMIT 1',(provider,scope,stamp(cutoff))).fetchone()
        if row is None:
            return None
        result={'bundle_id':row[0],'available_at':row[1],'published_at':None,
                'status':'observed_snapshot_only','model_eligible':False,'observations':[]}
        for endpoint,fetched,published,sha,body in self.db.execute(
                'SELECT endpoint,fetched_at,published_at,sha256,body FROM provider_observations WHERE bundle_id=? ORDER BY endpoint',(row[0],)):
            if not isinstance(body,bytes) or hashlib.sha256(body).hexdigest()!=sha:
                raise ValueError('Archive payload integrity check failed')
            result['observations'].append({'endpoint':endpoint,'fetched_at':fetched,
                'published_at':published,'sha256':sha,'payload':json.loads(body)})
        return result


def capture_fpl(archive,season):
    observations=tuple(fetch(FPL+endpoint+'/') for endpoint in ('bootstrap-static','fixtures'))
    counts=validate_fpl(observations,season)
    bundle=archive.save('fpl',season,observations)
    return {'bundle_id':bundle,'provider':'fpl','season':season,**counts,'model_eligible':False}


def capture_coverage(archive,league,year,*,api_key=None):
    if league<1 or year<2000:
        raise ValueError('Invalid league or season')
    key=api_key if api_key is not None else os.environ.get('API_FOOTBALL_KEY')
    if not key:
        raise ValueError('API_FOOTBALL_KEY is not configured')
    endpoint=API_FOOTBALL+'leagues?'+urlencode({'id':league,'season':year})
    observation=fetch(endpoint,api_key=key)
    coverage=validate_coverage(observation,league,year)
    bundle=archive.save('api_football',f'{league}:{year}',(observation,))
    return {'bundle_id':bundle,'provider':'api_football','coverage':coverage,'model_eligible':False}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db',default=os.environ.get('PREMATCH_ARCHIVE_DB','data/prematch_archive.sqlite3'))
    commands=parser.add_subparsers(dest='command',required=True)
    fpl=commands.add_parser('fpl');fpl.add_argument('--season',required=True)
    api=commands.add_parser('coverage');api.add_argument('--league',type=int,default=39)
    api.add_argument('--season',type=int,required=True)
    args=parser.parse_args()
    archive=Archive(args.db)
    try:
        result=(capture_fpl(archive,args.season) if args.command=='fpl'
                else capture_coverage(archive,args.league,args.season))
        print(json.dumps(result,ensure_ascii=False))
    except (ValueError,sqlite3.Error) as error:
        parser.exit(1,str(error)+'\n')
    finally:
        archive.close()


if __name__=='__main__':
    main()
