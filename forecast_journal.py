"""Manual, append-only baseline forecast journal. No network or scheduled work."""
import argparse
from datetime import datetime, timezone, timedelta
import hashlib
import inspect
import json
from pathlib import Path
import re
import sqlite3


def now():
    return datetime.now(timezone.utc)


def utc(value):
    if isinstance(value,str):value=datetime.fromisoformat(value.replace('Z','+00:00'))
    if not isinstance(value,datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError('Timezone-aware timestamp required')
    return value.astimezone(timezone.utc)


def canonical(value):
    return json.dumps(value,sort_keys=True,ensure_ascii=False,allow_nan=False,separators=(',',':'))


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


class Journal:
    def __init__(self,path):
        self.db=sqlite3.connect(path,timeout=10)
        self.db.execute('PRAGMA foreign_keys=ON')
        self.db.executescript('''
          CREATE TABLE IF NOT EXISTS forecast_journal(
            id INTEGER PRIMARY KEY,
            fixture_key TEXT UNIQUE NOT NULL,
            payload TEXT NOT NULL,
            previous_hash TEXT NOT NULL,
            entry_hash TEXT UNIQUE NOT NULL
          );
          CREATE TRIGGER IF NOT EXISTS forecast_no_update BEFORE UPDATE ON forecast_journal
            BEGIN SELECT RAISE(ABORT,'Forecast journal is append-only'); END;
          CREATE TRIGGER IF NOT EXISTS forecast_no_delete BEFORE DELETE ON forecast_journal
            BEGIN SELECT RAISE(ABORT,'Forecast journal is append-only'); END;
        ''')

    def close(self):self.db.close()

    def verify(self):
        previous='0'*64
        for _,key,body,prev,current in self.db.execute('SELECT * FROM forecast_journal ORDER BY id'):
            payload=json.loads(body)
            if (prev!=previous or current!=digest({'previous_hash':prev,'payload':payload})
                    or key!=digest(payload['fixture'])
                    or payload['history_hash']!=digest(payload['history'])):
                raise ValueError('Forecast journal integrity failure')
            previous=current
        return previous

    def capture(self,raw,*,fixture_id,home,away,season,kickoff,source_url):
        # Baseline functions are imported unchanged from the actual main application.
        from streamlit_app import feldolgozas, becsles, goltabla, pontos_eredmenyek
        captured=utc(now());kickoff=utc(kickoff)
        if not re.fullmatch(r'20\d\d/\d\d',season):raise ValueError('Invalid season')
        year=int(season[:4])
        if season[-2:]!=str(year+1)[-2:]:raise ValueError('Invalid consecutive season')
        if not datetime(year,7,1,tzinfo=timezone.utc)<=kickoff<datetime(year+1,7,1,tzinfo=timezone.utc):
            raise ValueError('Kickoff outside selected season')
        if not isinstance(fixture_id,str) or not fixture_id.strip() or home==away:
            raise ValueError('Invalid fixture identity')
        expected=f'https://www.football-data.co.uk/mmz4281/{year%100:02d}{(year+1)%100:02d}/E0.csv'
        if source_url!=expected:raise ValueError('Unexpected season/source reference')
        if not isinstance(raw,bytes) or len(raw)>12*1024*1024:raise ValueError('Invalid CSV body')
        if kickoff<=captured+timedelta(minutes=5):raise ValueError('Forecast must precede kickoff by over five minutes')
        matches=feldolgozas(raw)
        boundary=min(captured.date(),kickoff.date())
        history=sorted((m for m in matches if datetime(year,7,1).date()<=m[4]<boundary),
                       key=lambda m:(m[4],m[0],m[1]))
        if len({(m[0],m[1],m[4]) for m in history})!=len(history):
            raise ValueError('Duplicate historical fixture')
        if len(history)<60 or sum(m[0]==home for m in history)<3 or sum(m[1]==away for m in history)<3:
            raise ValueError('Insufficient history: 60 league, 3 home, 3 away required')
        p,lh,la,nh,na=becsles(history,home,away)
        stored_history=[[*m[:4],m[4].isoformat()] for m in history]
        fixture={'league':'E0','season':season,'fixture_id':fixture_id.strip(),
                 'home':home,'away':away,'kickoff_utc':kickoff.isoformat()}
        payload={'version':'prospective-baseline-v1','fixture':fixture,
                 'observed_at':captured.isoformat(),'recorded_at':None,
                 'source_url':source_url,'raw_sha256':hashlib.sha256(raw).hexdigest(),
                 'source_status':'locally_observed_csv_not_independently_authenticated',
                 'history':stored_history,'history_hash':digest(stored_history),
                 'history_policy':'dates_strictly_before_observation_utc_day_and_fixture_utc_day',
                 'model':'unchanged_main_baseline','model_code_hash':hashlib.sha256(
                     ''.join(inspect.getsource(f) for f in (becsles,goltabla,pontos_eredmenyek)).encode()).hexdigest(),
                 'lambdas':[lh,la],'one_x_two':p,'top5':pontos_eredmenyek(lh,la),
                 'counts':[len(history),nh,na]}
        try:
            self.db.execute('BEGIN IMMEDIATE')
            previous=self.verify()
            recorded=utc(now())
            if recorded<captured or kickoff<=recorded+timedelta(minutes=5):
                raise ValueError('Clock moved backwards or kickoff too close at commit')
            payload['recorded_at']=recorded.isoformat()
            key=digest(fixture)
            # Same provider fixture cannot be re-entered under a changed kickoff/team.
            for body, in self.db.execute('SELECT payload FROM forecast_journal'):
                old=json.loads(body)['fixture']
                if (old['league'],old['season'])==('E0',season) and (
                        old['fixture_id']==fixture_id.strip() or (old['home'],old['away'])==(home,away)):
                    raise ValueError('Fixture already has a frozen forecast')
            hashed=digest({'previous_hash':previous,'payload':payload})
            self.db.execute('INSERT INTO forecast_journal(fixture_key,payload,previous_hash,entry_hash) VALUES(?,?,?,?)',
                            (key,canonical(payload),previous,hashed))
            self.db.commit()
            return {'entry_hash':hashed,'payload':payload}
        except Exception:
            self.db.rollback()
            raise

    def export(self):
        self.db.execute('BEGIN')
        try:
            root=self.verify()
            entries=[{'payload':json.loads(body),'previous_hash':prev,'entry_hash':h}
                     for body,prev,h in self.db.execute('SELECT payload,previous_hash,entry_hash FROM forecast_journal ORDER BY id')]
            self.db.commit()
            return {'format':'forecast-journal-export-v1','count':len(entries),'root_hash':root,'entries':entries}
        except Exception:
            self.db.rollback();raise


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--db',required=True)
    sub=parser.add_subparsers(dest='action',required=True)
    capture=sub.add_parser('capture')
    for name in ('csv','fixture-id','home','away','season','kickoff','source-url'):
        capture.add_argument('--'+name,required=True)
    export=sub.add_parser('export');export.add_argument('--output',required=True)
    sub.add_parser('verify')
    args=parser.parse_args();journal=Journal(args.db)
    try:
        if args.action=='capture':
            result=journal.capture(Path(args.csv).read_bytes(),fixture_id=args.fixture_id,
                home=args.home,away=args.away,season=args.season,kickoff=args.kickoff,source_url=args.source_url)
            print(canonical({'entry_hash':result['entry_hash'],'recorded_at':result['payload']['recorded_at']}))
        elif args.action=='export':
            if Path(args.output).resolve()==Path(args.db).resolve():
                raise ValueError('Export must not overwrite the journal database')
            Path(args.output).write_text(canonical(journal.export())+'\n',encoding='utf-8')
        else:print(journal.verify())
    finally:journal.close()


if __name__=='__main__':main()
