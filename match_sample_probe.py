"""Fixed historical fixture audit, never an input to pre-match predictions."""
from datetime import datetime, timezone
import hashlib
import json
import math

from prematch_archive import Archive, API_FOOTBALL, fetch, stamp

FIXTURE_URL=API_FOOTBALL+'fixtures?league=39&season=2024&date=2024-08-16'
TEAM_IDS={33,36}
ERROR='A lekérés vagy az adatellenőrzés nem sikerült. A nyers válasz nem jelenik meg.'
DIAG_MESSAGES={
    'plan':'A szolgáltató csomag- vagy idénykorlátozást jelzett ennél a mérkőzéslekérésnél.',
    'auth':'A szolgáltató hitelesítési vagy hozzáférési hibát jelzett.',
    'quota':'A szolgáltató lekérési vagy sebességkorlátot jelzett.',
    'request':'A szolgáltató hibás vagy nem támogatott lekérési paramétert jelzett.',
    'provider':'A szolgáltató hibát jelzett; a pontos válasz nem jelenik meg.',
    'empty':'A szolgáltató nem adott mérkőzést erre a liga–idény–nap lekérésre.',
    'envelope':'A szolgáltatói válasz formátuma vagy lapozása eltér a várttól.',
    'identity':'Érkezett mérkőzés, de nem egyezik az elvárt liga, idény, nap, csapat vagy lezárt státusz.',
    'transport':'A HTTP- vagy hálózati lekérés nem sikerült.',
    'valid':'A megismételt egyetlen mérkőzéslekérés és az azonosítás most sikerült. A részadatok még nincsenek ezzel ellenőrizve.',
    'local':'A helyi mentés vagy ellenőrzés nem sikerült.',
    'unavailable':'Ez a diagnózis csak a mai, részlekérések előtt elakadt saját mérkőzéspróbához indítható.',
    'busy':'A mai egyszeri diagnózis már elindult. Új szolgáltatói lekérés nem történik.',
}


def provider_failure(data):
    """Classify private provider error text into a fixed code; never return text."""
    errors=data.get('errors') if isinstance(data,dict) else None
    if not errors:
        return None
    text=json.dumps(errors,ensure_ascii=True).lower()
    if any(token in text for token in ['rate limit','ratelimit','too many','request limit','quota']):
        return 'quota'
    if any(token in text for token in ['subscription','free plan','season','plan']):
        return 'plan'
    if any(token in text for token in ['token','api-key','api key','access','permission']):
        return 'auth'
    if any(token in text for token in ['parameter','date','fixture','league']):
        return 'request'
    return 'provider'


def diagnose_fixture(api_key,db_path):
    """One additional GET only after an initial failure that made at most one GET.

    Successful/fuller audits cannot use this path. Shared daily reservation and
    persistent reuse keep total requests <= 2 for this failed-audit recovery path.
    """
    at=datetime.now(timezone.utc);result={'checked_at':stamp(at),'code':'local'}
    archive=None
    if not isinstance(api_key,str) or not api_key.strip():
        return {**result,'code':'unavailable'}
    try:
        archive=Archive(db_path);db=archive.db;day=at.date().isoformat()
        fingerprint=hashlib.sha256(api_key.encode()).hexdigest()
        db.execute('CREATE TABLE IF NOT EXISTS match_sample_diagnoses(day TEXT PRIMARY KEY, result TEXT)')
        db.commit();db.execute('BEGIN IMMEDIATE')
        previous=db.execute('SELECT result FROM match_sample_diagnoses WHERE day=?',(day,)).fetchone()
        audit=db.execute('SELECT fingerprint,result FROM match_sample_checks WHERE day=?',(day,)).fetchone()
        saved=json.loads(audit[1]) if audit and audit[1] else None
        if (not audit or audit[0]!=fingerprint or not saved or saved.get('ok') is not False or saved.get('parts')!={}):
            db.rollback();return {**result,'code':'unavailable'}
        if previous:
            db.rollback();return json.loads(previous[0]) if previous[0] else {**result,'code':'busy'}
        db.execute('INSERT INTO match_sample_diagnoses VALUES(?,NULL)',(day,));db.commit()
        try:
            observation=fetch(FIXTURE_URL,api_key=api_key)
        except Exception:
            result['code']='transport'
        else:
            try:
                data=json.loads(observation.body)
                code=provider_failure(data)
                if code:
                    result['code']=code
                else:
                    items=rows(observation)
                    if not items:
                        result['code']='empty'
                    else:
                        try:
                            fixture_identity(items)
                        except Exception:
                            result['code']='identity'
                        else:
                            result['code']='valid'
                            archive.save('api_football_sample','2024-08-16:fixture-diagnosis',(observation,))
            except Exception:
                result['code']='envelope'
        with db:
            db.execute('UPDATE match_sample_diagnoses SET result=? WHERE day=?',(json.dumps(result),day))
        return result
    except Exception:
        return {**result,'code':'local'}
    finally:
        if archive is not None:
            archive.close()


def rows(observation):
    data=json.loads(observation.body)
    if (not isinstance(data,dict) or data.get('errors') or
        not isinstance(data.get('response'),list) or data.get('results')!=len(data['response']) or
        not isinstance(data.get('paging',{}),dict) or data.get('paging',{}).get('total',1)>1):
        raise ValueError('Invalid provider envelope')
    return data['response']


def fixture_identity(items):
    if len(items)!=1:
        raise ValueError('Exactly one fixture required')
    item=items[0]
    fixture=item['fixture'];league=item['league'];teams=item['teams']
    kickoff=datetime.fromisoformat(fixture['date'].replace('Z','+00:00'))
    if (type(fixture['id']) is not int or not 0<fixture['id']<10**12 or
        league['id']!=39 or league['season']!=2024 or
        kickoff.tzinfo is None or kickoff.astimezone(timezone.utc).date().isoformat()!='2024-08-16' or
        fixture['status']['short']!='FT' or teams['home']['id']!=33 or teams['away']['id']!=36):
        raise ValueError('Fixture identity mismatch')
    return fixture['id']


def paired_teams(items):
    ids=[item['team']['id'] for item in items]
    if len(ids)!=2 or set(ids)!=TEAM_IDS:
        raise ValueError('Team identity mismatch')


def numeric_xg(value):
    if type(value) not in (str,int,float):
        return None
    try:
        number=float(value)
    except (ValueError,OverflowError):
        return None
    return number if math.isfinite(number) and number>=0 else None


def summarize(kind,items,fixture_id):
    if not items:
        return {'state':'empty','count':0}
    if kind in ('statistics','lineups'):
        paired_teams(items)
    if kind=='statistics':
        xg={};counts=[]
        for item in items:
            stats=item['statistics']
            if not isinstance(stats,list) or any(not isinstance(s,dict) for s in stats):
                raise ValueError('Invalid statistics')
            counts.append(sum(s.get('value') is not None for s in stats))
            values=[numeric_xg(s.get('value')) for s in stats if s.get('type')=='expected_goals']
            if len(values)>1:
                raise ValueError('Duplicate xG statistic')
            xg[str(item['team']['id'])]=values[0] if values else None
        return {'state':'present' if all(counts) else 'partial','count':sum(counts),'xg':xg}
    if kind=='lineups':
        ids=[];counts=[]
        for item in items:
            players=item['startXI']
            if not isinstance(players,list):
                raise ValueError('Invalid lineup')
            current=[p['player']['id'] for p in players]
            if any(type(i) is not int or i<=0 for i in current) or len(set(current))!=len(current) or len(current)>11:
                raise ValueError('Invalid player identity')
            ids+=current;counts.append(len(current))
        if len(set(ids))!=len(ids):
            raise ValueError('Player on both teams')
        return {'state':'present' if counts==[11,11] else 'partial','count':sum(counts)}
    for item in items:
        if item['fixture']['id']!=fixture_id or item['team']['id'] not in TEAM_IDS or type(item['player']['id']) is not int:
            raise ValueError('Injury identity mismatch')
    return {'state':'present','count':len(items)}


def probe(api_key,db_path):
    """One shared batch per UTC day, max four GETs. Persist only safe result text.

    Repeated clicks reuse the result. A restart cannot reset the guard unless the
    local SQLite file is lost. No key or provider exception is stored in result.
    """
    at=datetime.now(timezone.utc)
    result={'checked_at':stamp(at),'ok':False,'model_eligible':False,'parts':{}}
    if not isinstance(api_key,str) or not api_key.strip():
        return {**result,'message':'Nincs beolvasható API_FOOTBALL_KEY.'}
    archive=None
    try:
        archive=Archive(db_path);db=archive.db
        day=at.date().isoformat();fingerprint=hashlib.sha256(api_key.encode()).hexdigest()
        db.execute('CREATE TABLE IF NOT EXISTS match_sample_checks(day TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, result TEXT)')
        db.commit();db.execute('BEGIN IMMEDIATE')
        previous=db.execute('SELECT fingerprint,result FROM match_sample_checks WHERE day=?',(day,)).fetchone()
        if previous:
            db.rollback()
            if previous[0]==fingerprint and previous[1]:
                return json.loads(previous[1])
            return {**result,'message':'A mai közös mérkőzéspróba már elindult vagy elfogyott. Új próba legkorábban holnap.'}
        db.execute('INSERT INTO match_sample_checks VALUES(?,?,NULL)',(day,fingerprint));db.commit()
        try:
            observation=fetch(FIXTURE_URL,api_key=api_key)
            fixture_id=fixture_identity(rows(observation))
            archive.save('api_football_sample','2024-08-16:fixture',(observation,))
            result.update(ok=True,fixture_id=fixture_id,message='A mérkőzést azonosítottuk; az egyes adattípusok eredménye alább látható.')
            for kind,path in [('statistics','fixtures/statistics'),('lineups','fixtures/lineups'),('injuries','injuries')]:
                try:
                    observation=fetch(API_FOOTBALL+path+'?fixture='+str(fixture_id),api_key=api_key)
                    summary=summarize(kind,rows(observation),fixture_id)
                    archive.save('api_football_sample',f'{fixture_id}:{kind}',(observation,))
                    result['parts'][kind]=summary
                except Exception:
                    result['parts'][kind]={'state':'error','message':ERROR}
        except Exception:
            result['message']=ERROR
        with db:
            db.execute('UPDATE match_sample_checks SET result=? WHERE day=? AND fingerprint=?',
                       (json.dumps(result,allow_nan=False),day,fingerprint))
        return result
    except Exception:
        return {**result,'ok':False,'message':ERROR}
    finally:
        if archive is not None:
            archive.close()


def render(st,key,db_path):
    st.subheader('Egy konkrét mérkőzés adatpróbája')
    st.write('Manchester United–Fulham, 2024. augusztus 16. (Premier League, 2024/25).')
    st.caption('Külön, közös keret: naponta egy próbasorozat, legfeljebb 4 API-hívás. '
               'Az ismételt kattintás a mentett eredményt mutatja. Csak az alábbi gomb indítja.')
    st.info('Utólag lekért történeti adat. Nem bizonyítja, mit tudhattunk a kezdés előtt; '
            'nem használjuk múltbeli előrejelzéshez vagy a modell módosításához.')
    st.caption('Ha az első mérkőzéslekérés elakadt: az alábbi külön diagnózis egyszer, '
               'legfeljebb 1 további API-hívással megkülönbözteti a szolgáltatói korlátozást, '
               'az üres választ és az azonosítási eltérést. A napi sikeres próbát nem indítja újra.')
    if st.button('Sikertelen mérkőzéspróba okának ellenőrzése',disabled=not bool(key),key='match_diagnosis_button'):
        with st.spinner('Hiba okának ellenőrzése…'):
            diagnosis=diagnose_fixture(key,db_path)
        st.caption('Diagnózis ideje (UTC): '+diagnosis['checked_at'])
        st.info(DIAG_MESSAGES[diagnosis['code']])
    if st.button('2024/25-ös mérkőzés adatainak ellenőrzése',disabled=not bool(key),key='match_sample_button'):
        with st.spinner('Mérkőzésadatok ellenőrzése…'):
            result=probe(key,db_path)
        st.caption('Ellenőrzés ideje (UTC): '+result['checked_at'])
        if not result['ok']:
            st.warning(result['message']);return
        st.success(result['message'])
        labels={'statistics':'Mérkőzés-statisztikák','lineups':'Kezdőcsapatok','injuries':'Hiányzóbejegyzések'}
        states={'present':'Adat érkezett','partial':'Részleges adat','empty':'Üres válasz – nem igazolja az adatok vagy hiányzók hiányát','error':'Sikertelen lekérés / ellenőrzés'}
        st.table([{'Adattípus':labels[k],'Eredmény':states[v['state']],'Bejegyzések':v.get('count',0) if v['state']!='error' else 'Ismeretlen'} for k,v in result['parts'].items()])
        xg=result['parts'].get('statistics',{}).get('xg',{})
        st.write('xG (hazai / vendég): '+ ' / '.join('Nincs igazolt adat' if xg.get(team) is None else str(xg[team]) for team in ['33','36']))
        st.caption('Az xG itt a már lejátszott mérkőzés adata. Hiányzó értéket nem helyettesítünk nullával. '
                   'A hiányzólista teljességét és korabeli elérhetőségét ez a próba nem igazolja.')
