"""Click-only API-FOOTBALL diagnostic. No credentials or raw responses reach the UI."""
from datetime import datetime, timedelta, timezone
from collections.abc import Mapping
import hashlib
import os
import streamlit as st

from prematch_archive import Archive, capture_coverage, stamp


class CheckLimit(Exception):
    pass


CONFIG_MESSAGES = {
    'ready': 'Kulcs beállítva. Az érvényességét csak a kapcsolati próba ellenőrzi.',
    'unreadable': 'A Secrets beállítás nem olvasható. Hiányzó fájl vagy hibás TOML-formátum is okozhatja. Ellenőrizd a Manage app → Settings → Secrets mentését; a kulcsot ne küldd el.',
    'empty_store': 'Az alkalmazás üres Secrets beállítást lát. Ellenőrizd, hogy ennek az alkalmazásnak a Settings → Secrets mezőjébe mentettél-e.',
    'missing': 'A Secrets olvasható, de a legfelső szinten nincs API_FOOTBALL_KEY bejegyzés. Ellenőrizd a pontos nevet és a mentést ebben az alkalmazásban.',
    'nested': 'Az API_FOOTBALL_KEY egy [szakasz] alatt található. Helyezd a teljes bejegyzést minden [szakasz] elé, majd Save. A többi beállítást hagyd meg.',
    'invalid': 'Az API_FOOTBALL_KEY bejegyzés megvan, de nem nemüres szöveg. Az érték idézőjelek között szerepeljen, majd Save. A kulcsot ne küldd el.',
}


def key_configuration(secrets):
    """Return a credential privately, plus a fixed, value-free diagnostic code.

    Nested credentials are detected but never selected implicitly. Neither section
    names, secret names other than our fixed key, values nor exceptions are output.
    """
    name='API_FOOTBALL_KEY'
    try:
        if name in secrets:
            value=secrets[name]
            if isinstance(value,str) and value.strip():
                return value.strip(),'ready'
            status='invalid'
        else:
            def contains_nested_key(mapping,depth=0):
                if depth>=8:
                    return False
                for value in mapping.values():
                    if isinstance(value,Mapping):
                        if name in value or contains_nested_key(value,depth+1):
                            return True
                return False
            status='nested' if contains_nested_key(secrets) else 'missing' if len(secrets) else 'empty_store'
    except Exception:
        status='unreadable'
    value=os.environ.get(name)
    if isinstance(value,str) and value.strip():
        return value.strip(),'ready'
    return None,status


def configured_key(secrets):
    """Compatibility wrapper retaining root Secrets / environment precedence."""
    return key_configuration(secrets)[0]


def reserve_attempt(db,at):
    """Shared across sessions in this SQLite store; count failures as attempts too."""
    current=stamp(at)
    day=at.astimezone(timezone.utc).date().isoformat()
    db.execute('CREATE TABLE IF NOT EXISTS api_check_attempts(at TEXT NOT NULL)')
    db.commit()
    try:
        db.execute('BEGIN IMMEDIATE')
        count=db.execute('SELECT COUNT(*) FROM api_check_attempts WHERE substr(at,1,10)=?',(day,)).fetchone()[0]
        last=db.execute('SELECT MAX(at) FROM api_check_attempts').fetchone()[0]
        if count>=5:
            raise CheckLimit('A mai öt kapcsolati próba már elfogyott. Próbáld újra holnap.')
        if last and at-datetime.fromisoformat(last)<timedelta(seconds=60):
            raise CheckLimit('Várj legalább egy percet a következő új lekérés előtt.')
        db.execute('INSERT INTO api_check_attempts VALUES(?)',(current,))
        db.commit()
    except Exception:
        db.rollback()
        raise


def diagnostic(api_key,season,db_path):
    """Return only fixed labels, booleans and timestamps; never exception text."""
    at=datetime.now(timezone.utc)
    result={'ok':False,'season':season,'checked_at':stamp(at)}
    if not api_key:
        return {**result,'message':'Az API_FOOTBALL_KEY nincs beállítva.'}
    archive=None
    try:
        archive=Archive(db_path)
        reserve_attempt(archive.db,at)
        raw=capture_coverage(archive,39,season,api_key=api_key)
        coverage=raw.get('coverage',{})
        if not isinstance(coverage,dict):
            raise ValueError('Invalid coverage')
        fixture=coverage.get('fixtures',{})
        if not isinstance(fixture,dict):
            fixture={}
        def flag(container,name):
            value=container.get(name)
            return value if type(value) is bool else None
        safe={'Sérülések / hiányzók':flag(coverage,'injuries'),
              'Kezdőcsapatok':flag(fixture,'lineups'),
              'Mérkőzés-statisztikák':flag(fixture,'statistics_fixtures'),
              'Játékosstatisztikák':flag(fixture,'statistics_players')}
        return {**result,'ok':True,'coverage':safe,
                'message':'A kapcsolat működik, a kiválasztott liga és idény elérhető.'}
    except CheckLimit as error:
        return {**result,'message':str(error)}
    except Exception:
        return {**result,'message':'A próba nem sikerült. Lehetséges ok: kulcs, csomag, idénykorlátozás, hálózati vagy helyi mentési hiba. A kulcs és a szolgáltatói válasz nem kerül megjelenítésre.'}
    finally:
        if archive is not None:
            archive.close()


@st.cache_data(ttl=3600,show_spinner=False)
def cached_diagnostic(season,db_path,key_fingerprint,_api_key):
    # The secret is excluded from Streamlit's cache key; only its digest is hashed.
    return diagnostic(_api_key,season,db_path)


def run():
    st.header('API-FOOTBALL kapcsolati próba')
    st.write('Ellenőrizd, milyen adatok érhetők el a Premier League-hez az előfizetésedben.')
    key,status=key_configuration(st.secrets)
    st.info(CONFIG_MESSAGES[status])
    st.caption('Beállításellenőrző: 2. verzió. Nem jelenít meg kulcsot vagy kulcsrészletet.')
    year=datetime.now(timezone.utc).year
    season=st.selectbox('Idény kezdőéve',list(range(year,year-5,-1)),
                        format_func=lambda value:f'{value}/{str(value+1)[-2:]}',key='api_check_season')
    st.caption('Csak a gomb indít ellenőrzést. Az eredményt legfeljebb egy órán át újrahasználjuk. '
               'Új lekérésből legfeljebb öt engedélyezett naponta, az alkalmazás felhasználói között közösen.')
    if st.button('Kapcsolat és lefedettség ellenőrzése',disabled=not bool(key),key='api_check_button'):
        path=os.environ.get('PREMATCH_ARCHIVE_DB','data/prematch_archive.sqlite3')
        with st.spinner('Kapcsolat ellenőrzése…'):
            result=cached_diagnostic(season,path,hashlib.sha256(key.encode()).hexdigest(),_api_key=key)
        st.caption('Az ellenőrzés ideje (UTC): '+result['checked_at'])
        if result['ok']:
            st.success(result['message'])
            st.table([{'Adattípus':name,'Lefedettség':
                       'Elérhető' if value is True else 'Nem elérhető' if value is False else 'Nincs közölt adat'}
                      for name,value in result['coverage'].items()])
        else:
            st.warning(result['message'])
    st.caption('A lefedettségi jelző nem garantál teljes adatot minden meccshez. '
               'A statisztikák elérhetősége önmagában nem igazolja az xG meglétét. '
               'Ez a próba nem módosítja a modell becsléseit.')

