"""Owner-authorized Streamlit controls; a successful save means cloud commit."""
import hmac
import json
import os
import streamlit as st
from forecast_journal import canonical, utc
from forecast_cloud import (GitHubArchive, MAX_JSON, restore_journal, validate_state,
                            append_result, evaluate)

ALIASES={'Manchester City':'Man City','Manchester United':'Man United','Newcastle United':'Newcastle',
         'Tottenham Hotspur':'Tottenham','Wolverhampton Wanderers':'Wolves',
         'Nottingham Forest':"Nott'm Forest",'West Ham United':'West Ham',
         'Brighton and Hove Albion':'Brighton','Leeds United':'Leeds',
         'Ipswich Town':'Ipswich','Leicester City':'Leicester','AFC Bournemouth':'Bournemouth'}


def setting(name):
    try:value=st.secrets.get(name)
    except Exception:value=None
    return value or os.environ.get(name,'')


def authorized():
    token=setting('FORECAST_ARCHIVE_TOKEN');password=setting('FORECAST_JOURNAL_PASSWORD')
    if not token or not password or not setting('FORECAST_ARCHIVE_REPOSITORY'):
        st.info('A felhőnapló még nincs beállítva. Privát GitHub-archívum, külön hozzáférés és naplójelszó szükséges.')
        return False
    if len(str(password))<12:
        st.info('A naplóhoz legalább 12 karakteres saját jelszót állíts be.');return False
    entered=st.text_input('Napló jelszava',type='password',key='forecast_password')
    if not entered or not hmac.compare_digest(str(entered).encode('utf-8'),str(password).encode('utf-8')):
        st.caption('A napló eléréséhez és módosításához add meg a saját naplójelszavadat.')
        return False
    return True


def cloud():
    return GitHubArchive(setting('FORECAST_ARCHIVE_TOKEN'),
        setting('FORECAST_ARCHIVE_REPOSITORY'))


def season_for(kickoff):
    day=utc(kickoff).date();year=day.year if day.month>=7 else day.year-1
    return f'{year}/{(year+1)%100:02d}',f'https://www.football-data.co.uk/mmz4281/{year%100:02d}{(year+1)%100:02d}/E0.csv'


def download_csv(url):
    from urllib.request import Request, urlopen
    with urlopen(Request(url,headers={'User-Agent':'FootballValueAI/forecast-journal'}),timeout=25) as response:
        raw=response.read(12*1024*1024+1)
    if len(raw)>12*1024*1024:raise ValueError('CSV too large')
    return raw


def capture_event(event):
    st.subheader('Pontos tipp mentése a felhőnaplóba')
    st.caption('Az aktuális baseline-t mentjük a kezdés előtt. A kísérleti modellek itt nem aktívak.')
    if not authorized():return
    season,source=season_for(event['commence_time'])
    identity=(event['id'],event['home_team'],event['away_team'],event['commence_time'])
    if st.button('Pontos tipp előkészítése',key='prepare_frozen_forecast'):
        try:
            raw=download_csv(source)
            from streamlit_app import feldolgozas
            names=sorted({t for m in feldolgozas(raw) for t in m[:2]})
            st.session_state['_forecast_pending']={'identity':identity,'raw':raw,'names':names}
        except Exception:
            st.error('A történeti eredmények betöltése nem sikerült. Nem mentettünk tippet.')
    pending=st.session_state.get('_forecast_pending')
    if not pending or tuple(pending['identity'])!=identity:return
    names=pending['names']
    with st.form('freeze_forecast_form'):
        selected=[]
        for side,label in [('home_team','Napló: hazai csapat'),('away_team','Napló: vendégcsapat')]:
            wanted=ALIASES.get(event[side],event[side]);index=names.index(wanted) if wanted in names else None
            selected.append(st.selectbox(label,names,index=index,placeholder='Válaszd ki az API-val egyező csapatot'))
        confirmed=st.checkbox('Ellenőriztem a csapatokat és a kezdési időt; ugyanaz a mérkőzés.')
        save=st.form_submit_button('Pontos tipp végleges mentése')
    if save:
        if not confirmed or any(v is None for v in selected):
            st.warning('A mentéshez válaszd ki és ellenőrizd mindkét csapatot.');return
        def mutate(state):
            j=restore_journal(state['journal'])
            try:
                j.capture(pending['raw'],fixture_id=str(event['id']),home=selected[0],away=selected[1],
                    season=season,kickoff=event['commence_time'],source_url=source)
                state['journal']=j.export();return state
            finally:j.close()
        try:
            cloud().change(mutate)
            st.session_state.pop('_forecast_pending',None)
            st.success('A pontos tipp a felhőarchívumba került. A Tippek naplója oldalon visszanézheted.')
        except Exception:
            st.error('A felhőmentés nem igazolt. Lehet meglévő tipp, túl közeli kezdés, kevés adat vagy tárolási hiba. Frissítsd a naplót az újrapróbálás előtt.')


def run():
    st.title('Tippek naplója')
    st.caption('Meccs előtt mentett baseline-tippek • GitHub-felhőarchívum • kézzel ellenőrzött végeredmények')
    if not authorized():return
    st.button('Napló frissítése',key='refresh_forecast_archive')
    try:state,_=cloud().load()
    except Exception:
        st.error('A felhőnapló nem tölthető be. Privát tároló és megfelelő hozzáférés szükséges.')
        if st.button('Felhőnapló létrehozása a privát tárolóban'):
            try:
                cloud().initialize();st.rerun()
            except Exception:st.error('A felhőnapló nem hozható létre. Ellenőrizd a privát tárolót és a hozzáférést.')
        return
    if st.session_state.pop('_forecast_result_saved',False):st.success('Az eredmény a felhőarchívumba került.')
    st.caption('A mentett tippek a felhőből töltődtek be; a helyi Streamlit-fájl elvesztése nem törli őket.')
    st.download_button('Teljes napló letöltése',canonical(state),file_name='football-forecast-archive.json',mime='application/json')
    with st.expander('Biztonsági mentés visszaállítása'):
        uploaded=st.file_uploader('Korábban letöltött felhőnapló',type=['json'])
        st.caption('A visszaállítás csak a meglévő történet folytatását engedi; korábbi mentés nem törölhet újabb rekordot. A fájl eredete önmagában nem hitelesített.')
        if st.button('Biztonsági mentés visszaállítása',disabled=uploaded is None):
            try:
                raw=uploaded.getvalue()
                if len(raw)>MAX_JSON:raise ValueError('Too large')
                backup=validate_state(json.loads(raw))
                cloud().change(lambda _:backup)
                st.success('A mentés a felhőarchívumba került. Frissítsd a naplót.')
            except Exception:st.error('A mentés nem állítható vissza: sérült, eltérő vagy régebbi történet, illetve felhőhiba.')
    summary=evaluate(state)
    st.metric('Mentett tippek',len(state['journal']['entries']))
    st.metric('Értékelt mérkőzések',summary['evaluated'])
    st.caption(f"Eredményre vár: {summary['pending']} • Nem értékelhető: {summary['void']}")
    if summary['evaluated']:
        st.metric('Napló: első tipp találati aránya',f"{100*summary['means']['top1']:.1f}%")
        st.metric('Napló: top 5 találati aránya',f"{100*summary['means']['top5']:.1f}%")
        st.metric('Napló: pontoseredmény NLL',f"{summary['means']['nll']:.3f}")
        st.metric('Napló: 1X2 Brier',f"{summary['means']['brier']:.3f}")
    st.info('Az eredményeket kézzel ellenőrzöttként rögzítjük. Ez nem független időbélyeg-hitelesítés vagy fogadási profitmérés; kevés meccsből nem állapítható meg javulás.')
    entries=state['journal']['entries']
    if not entries:
        st.write('Még nincs mentett tipp. Az Oddsmozgás-nyomozó napi EPL-listájában válassz közelgő meccset.');return
    by_hash={e['entry_hash']:e['payload'] for e in entries}
    selected=st.selectbox('Mentett pontos tipp',list(by_hash),format_func=lambda h:
        f"{by_hash[h]['fixture']['home']} – {by_hash[h]['fixture']['away']} | {by_hash[h]['fixture']['kickoff_utc']}")
    p=by_hash[selected]
    st.write('Rögzítve (UTC): '+p['recorded_at'])
    st.dataframe([{'Hazai gól':h,'Vendég gól':a,'Becsült esély':q} for h,a,q in p['top5']],hide_index=True)
    st.caption('Az új eredménybejegyzés a korábbit megőrzi; az összesítés a legutóbbi állapotot használja.')
    with st.form('record_forecast_result'):
        status=st.selectbox('Eredmény állapota',['Végeredmény','Törölt / nem értékelhető'])
        h=st.number_input('Végeredmény: hazai gól',min_value=0,max_value=100,step=1)
        a=st.number_input('Végeredmény: vendég gól',min_value=0,max_value=100,step=1)
        kickoff=st.text_input('Tényleges kezdés (UTC, időzónával)',value=p['fixture']['kickoff_utc'],key='result_actual_kickoff_'+selected)
        source=st.text_input('Végeredmény nyilvános forrása',value=p['source_url'])
        reason=st.text_input('Törlés / javítás indoka')
        confirmed=st.checkbox('Ellenőriztem: befejezett mérkőzés, rendes játékidős eredmény, helyes csapatok és tényleges kezdés.')
        save=st.form_submit_button('Végeredmény rögzítése')
    if save:
        try:
            cloud().change(lambda current:append_result(current,selected,score=(int(h),int(a)),source_url=source,
                actual_kickoff=kickoff,confirmed_regulation=confirmed,
                status='completed' if status=='Végeredmény' else 'void',reason=reason))
            st.session_state['_forecast_result_saved']=True;st.rerun()
        except Exception:st.error('Az eredmény nem menthető. Ellenőrizd a befejezést, forrást és tényleges kezdést; ütközés vagy felhőhiba esetén frissítsd a naplót.')
