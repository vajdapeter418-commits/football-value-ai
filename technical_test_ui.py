"""Opt-in test-host UI; never reads secrets or production archives."""
from datetime import datetime, timedelta, timezone
import os
import streamlit as st
from market_backtest import backtest
from technical_test import TestStore, permitted, authorized


def _url():
    return getattr(getattr(st, 'context', None), 'url', '')


def _authorized():
    return authorized(getattr(st, 'user', None), os.environ.get('FVA_TECH_TEST_ALLOWED_EMAILS'))


def run():
    st.title('TESZT – biztonságos technikai tesztmód')
    st.warning('Kizárólag mesterséges TESZT adatok; nem valódi mérkőzés vagy fogadási ajánlat.')
    url = _url()
    if not permitted(url, os.environ.get('FVA_TECH_TEST_ENABLED')):
        st.error('A technikai tesztmód csak a kijelölt HTTPS tesztalkalmazásban engedélyezett.')
        return
    if not _authorized():
        st.error('A TESZT adatokhoz ellenőrzött bejelentkezés és külön hozzáférési engedély szükséges.')
        if st.button('TESZT bejelentkezés'):
            try:
                st.login()
            except Exception:
                st.error('A TESZT bejelentkezés nincs megfelelően beállítva.')
        return
    root = os.environ.get('FVA_TECH_TEST_ROOT')
    if not root:
        st.error('Nincs külön TESZT tároló. Mentés letiltva; nincs másik adatbázisra váltás.')
        return
    try:
        store = TestStore(root, url=url, enabled='1')
        state = store.load()
    except Exception:
        st.error('A külön TESZT tároló nem használható. Nincs átváltás másik tárolóra.')
        return
    st.caption('A folyamat újraindítása után a mentés visszaolvasható, ha a kötet megmarad. '
               'A felhős kötet tartóssága nincs igazolva; helyi fájl nem jelent felhős garanciát.')
    now = datetime.now(timezone.utc)
    with st.form('technical_test_match'):
        fixture = st.text_input('TESZT azonosító', value='proba-1')
        home = st.text_input('TESZT hazai név', value='A')
        away = st.text_input('TESZT vendégnév', value='B')
        kickoff = st.text_input('TESZT kezdés UTC', value=(now + timedelta(days=1)).isoformat())
        observed = st.text_input('TESZT odds megfigyelés UTC', value=now.isoformat())
        prices = {o: st.number_input('TESZT odds ' + o, min_value=1.01, value=v)
                  for o, v in [('home', 2.3), ('draw', 3.2), ('away', 3.0)]}
        if st.form_submit_button('TESZT mérkőzés és odds mentése'):
            try:
                store.save_match(fixture=fixture, home=home, away=away, kickoff=kickoff,
                                 observed_at=observed, prices=prices)
                state = store.load()
                st.success('TESZT adatok mentve és visszaolvasva.')
            except Exception:
                st.error('A TESZT mentés sikertelen. Ellenőrizd az adatokat és az időrendet.')
    st.subheader('Visszaolvasott TESZT adatok')
    st.write({'TESZT megfigyelések': len(state['observations']), 'TESZT eredmények': len(state['results'])})
    st.dataframe([dict(TESZT_meccs=e['payload']['fixture_id'], hazai=e['payload']['home'],
                       vendeg=e['payload']['away'], kezdes=e['payload']['kickoff'],
                       rogzitve=e['payload']['recorded_at'], odds=e['payload']['odds'][-1]['prices'])
                  for e in state['observations']])
    identities = sorted({e['payload']['fixture_id'] for e in state['observations']})
    if identities:
        with st.form('technical_test_result'):
            selected = st.selectbox('TESZT lezárt mérkőzés', identities)
            hg = st.number_input('TESZT hazai gól', min_value=0, max_value=100, value=1)
            ag = st.number_input('TESZT vendéggól', min_value=0, max_value=100, value=0)
            ended = st.text_input('TESZT befejezés UTC', value=now.isoformat())
            if st.form_submit_button('TESZT eredmény mentése'):
                try:
                    state = store.save_result(selected, home_goals=hg, away_goals=ag, ended_at=ended)
                    st.success('TESZT eredmény mentve.')
                except Exception:
                    st.error('Érvénytelen vagy még nem befejezett TESZT mérkőzés.')
    with st.form('technical_test_replay'):
        start = st.text_input('TESZT időszak kezdete UTC', value=(now - timedelta(days=30)).isoformat())
        end = st.text_input('TESZT időszak vége UTC (kizáró)', value=(now + timedelta(days=30)).isoformat())
        if st.form_submit_button('TESZT visszateszt futtatása'):
            try:
                report = backtest(store.load(), test_start=start, test_end=end)
                st.write({'TESZT értékelt': report['test_n'], 'TESZT kizárások': report['exclusions']})
                st.dataframe(report['rows'])
                st.caption('Mesterséges technikai visszajátszás; nem teljesítményigazolás.')
            except Exception:
                st.error('A TESZT visszateszt nem futtatható ezekkel az adatokkal.')
