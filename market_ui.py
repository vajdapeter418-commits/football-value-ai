"""Phone-friendly, owner-authorized market research view."""
import json

import streamlit as st
from forecast_cloud import ArchiveMissing
from forecast_journal import canonical, utc
from forecast_journal_ui import authorized, setting
from market_archive import MarketArchive
from market_backtest import backtest
from market_research import (append_observations, append_protocol, append_result,
                             available, delta_pp, parse_csv, source_status)


def cloud():
    return MarketArchive(setting('FORECAST_ARCHIVE_TOKEN'), setting('FORECAST_ARCHIVE_REPOSITORY'))


def _save(mutator):
    try:
        cloud().change(mutator)
        st.success('A piaci bejegyzés mentését a privát felhőarchívum visszaigazolta. Frissítsd a nézetet.')
    except Exception:
        st.error('A mentés nem igazolt. Ellenőrizd a mezőket és a forrást; frissíts a megismétlés előtt. Korábbi rekord nem írható felül.')


def _manual():
    names = st.text_input('Kimenetelek vesszővel elválasztva', value='home,draw,away')
    outcomes = [x.strip() for x in names.split(',')]
    if not 2 <= len(outcomes) <= 20 or len(set(outcomes)) != len(outcomes) or not all(outcomes):
        st.info('Adj meg 2–20 különböző kimenetelt.'); return
    with st.form('market_manual'):
        st.caption('Minden idő UTC és időzónás ISO-formátum, például 2026-11-01T12:00:00Z. Üres százalék = nem elérhető.')
        fixture = st.text_input('Fixture azonosító')
        home = st.text_input('Hazai csapat'); away = st.text_input('Vendégcsapat')
        sport = st.text_input('Sportág', value='football')
        market = st.text_input('Piac', value='1X2')
        line = st.text_input('Handicap / total vonal (ha nincs: none)', value='none')
        book = st.text_input('Eredeti fogadóiroda (a splits és odds azonos irodától)')
        kickoff = st.text_input('Kezdés UTC')
        publisher = st.text_input('Közlő oldal neve')
        original = st.text_input('Eredeti adatforrás neve')
        url = st.text_input('Eredeti közlés HTTPS URL')
        published = st.text_input('Közzététel UTC')
        observed = st.text_input('Megfigyelés UTC')
        original_text = st.text_area('Eredeti közlés szövege / pontos idézete')
        permission = st.selectbox('Felhasználási jogosultság', ['manual_reference', 'unknown', 'denied'])
        fetch = st.selectbox('Adatlekérés állapota', ['manual', 'not_available', 'error'])
        verified = st.checkbox('Az eredeti forrást, irodát és időpontot személyesen ellenőriztem')
        st.caption('A kézi ellenőrzés tulajdonosi nyilatkozat, nem független hitelesítés. API-integráció nincs bekapcsolva.')
        share_inputs = {}
        current_prices = {}
        for outcome in outcomes:
            st.subheader(outcome)
            ticket = st.text_input('Tickets % — ' + outcome, key='market_ticket_' + outcome)
            ticket_origin = st.selectbox('Tickets eredete — ' + outcome, ['reported', 'calculated_complement'], key='market_ticket_origin_' + outcome)
            handle = st.text_input('Handle % — ' + outcome, key='market_handle_' + outcome)
            handle_origin = st.selectbox('Handle eredete — ' + outcome, ['reported', 'calculated_complement'], key='market_handle_origin_' + outcome)
            share_inputs[outcome] = (ticket, ticket_origin, handle, handle_origin)
            current_prices[outcome] = st.text_input('Aktuális odds — ' + outcome, key='market_price_' + outcome)
        convention = st.selectbox('Aktuális odds formátuma', ['decimal', 'american'])
        marker = st.selectbox('Aktuális odds jelölője', ['snapshot', 'opening', '12h', 'closing'])
        st.caption('A fenti aktuális odds időpontja a megfigyelési idő. Ha bármely oddsot megadsz, minden kimenetel szükséges. Üresen is menthető a splits.')
        st.caption('Odds-idősor: JSON lista. Elem: at, kind (opening/12h/closing/snapshot), prices (minden kimenetel), convention (decimal/american), source (teljes forrásobjektum; elhagyva a fenti forrás). Külön korabeli időpontot ne örökíts későbbi közlésből.')
        odds = st.text_area('Odds-idősor JSON', value='[]')
        st.caption('Hírlista eleme: kind (injury/rotation/lineup/other), certainty (fact/assumption), text, source (teljes forrás, saját időbélyegekkel).')
        news = st.text_area('Meccs előtti hírek JSON', value='[]')
        hypothesis = st.text_area('Kutatási hipotézis (feltételezés)')
        explanation = st.text_area('Magyarázat / ismert korlátok')
        save = st.form_submit_button('Új megfigyelés végleges mentése')
    if save:
        try:
            source = {'publisher': publisher, 'original_source': original, 'original_bookmaker': book,
                      'url': url, 'published_at': published, 'observed_at': observed,
                      'original_text': original_text, 'permission': permission, 'fetch_status': fetch,
                      'verification': 'manual_verified' if verified else 'unverified'}
            points = json.loads(odds)
            if any(current_prices.values()):
                points.append({'at': observed, 'kind': marker, 'convention': convention,
                               'prices': {o: float(v) for o, v in current_prices.items()}})
            points.sort(key=lambda point: utc(point['at']))
            shares = {}
            for o, (ticket, ticket_origin, handle, handle_origin) in share_inputs.items():
                shares[o] = {'tickets': float(ticket) if ticket.strip() else None,
                             'tickets_origin': ticket_origin if ticket.strip() else 'unavailable',
                             'handle': float(handle) if handle.strip() else None,
                             'handle_origin': handle_origin if handle.strip() else 'unavailable'}
            for point in points:
                point.setdefault('source', source)
            record = {'fixture_id': fixture, 'home': home, 'away': away, 'sport': sport,
                      'market': market, 'line': line, 'bookmaker': book, 'kickoff': kickoff,
                      'source': source, 'outcomes': outcomes,
                      'shares': shares, 'odds': points, 'news': json.loads(news),
                      'hypothesis': hypothesis, 'explanation': explanation}
        except Exception:
            st.error('A JSON-mezők nem olvashatók. Nem történt mentés.'); return
        _save(lambda state: append_observations(state, [record]))


def _import():
    st.caption('UTF-8 CSV, egy observation_json oszloppal: soronként egy teljes megfigyelés. A teljes séma és mezőmagyarázat a docs/MARKET_RESEARCH.md fájlban. Legfeljebb 500 sor / 2 MiB; az import egy tranzakció.')
    st.download_button('Üres CSV-sablon', 'observation_json\n', file_name='market-import.csv', mime='text/csv')
    uploaded = st.file_uploader('Piaci CSV', type=['csv'], key='market_csv')
    if st.button('CSV ellenőrzése és új rekordként mentése', disabled=uploaded is None):
        try:
            records = parse_csv(uploaded.getvalue())
        except Exception:
            st.error('Érvénytelen vagy túl nagy CSV. Nem történt mentés.'); return
        _save(lambda state: append_observations(state, records))


def _observations(state, gap_threshold, max_age):
    entries = state['observations']
    st.caption(f'Mentett megfigyelések: {len(entries)}. Ellenőrizetlen / nem elérhető: {sum(not available(e["payload"]) for e in entries)}. Ezek mérési értékeit nem jelenítjük meg.')
    verified = [e for e in entries if available(e['payload'])]
    if not verified:
        st.info('Nincs ellenőrzött adat. Nincs élő splits-szolgáltató, scraping vagy demo-adat.'); return
    sports = sorted({e['payload']['sport'] for e in verified})
    books = sorted({e['payload']['bookmaker'] for e in verified})
    sport = st.selectbox('Sportág szűrése', ['Mind', *sports])
    book = st.selectbox('Iroda szűrése', ['Mind', *books])
    day = st.text_input('Kezdési dátum szűrése (UTC, YYYY-MM-DD; üres = mind)')
    match = st.text_input('Mérkőzés vagy fixture keresése')
    filtered = [e for e in verified if (sport == 'Mind' or e['payload']['sport'] == sport)
                and (book == 'Mind' or e['payload']['bookmaker'] == book)
                and (not day or utc(e['payload']['kickoff']).date().isoformat() == day)
                and (not match or match.casefold() in ' '.join(str(e['payload'][k]) for k in ('home', 'away', 'fixture_id')).casefold())]
    rows = []
    for entry in filtered:
        p = entry['payload']
        for outcome, share in p['shares'].items():
            gap = delta_pp(share)
            rows.append({'Meccs': p['home'] + ' – ' + p['away'], 'Piac': p['market'], 'Vonal': p['line'],
                         'Iroda': p['bookmaker'], 'Kimenetel': outcome,
                         'Tickets %': share['tickets'] if share['tickets'] is not None else 'nem elérhető',
                         'Handle %': share['handle'] if share['handle'] is not None else 'nem elérhető',
                         'Eltérés (százalékpont)': gap,
                         'Küszöb elérve': gap is not None and gap >= gap_threshold,
                         'Tickets eredet': share['tickets_origin'], 'Handle eredet': share['handle_origin'],
                         'Forrás': p['source']['publisher'], 'Eredeti adat': p['source']['original_source'],
                         'Forrásállapot': source_status(p, max_age_hours=max_age),
                         'Megfigyelve UTC': p['source']['observed_at'], 'Szerveren mentve UTC': p['recorded_at'],
                         'Előzetesen mentett': p['prospective']})
    st.dataframe(rows, hide_index=True)
    if not filtered:
        return
    by_hash = {e['entry_hash']: e['payload'] for e in filtered}
    selected = st.selectbox('Megfigyelés részletei', list(by_hash), format_func=lambda h:
                            f'{by_hash[h]["home"]} – {by_hash[h]["away"]} | {by_hash[h]["bookmaker"]} | {by_hash[h]["source"]["observed_at"]}')
    p = by_hash[selected]
    if any(s['tickets'] is not None for s in p['shares'].values()) and all(s['handle'] is None for s in p['shares'].values()):
        st.warning('Csak tickets adat: pénzarány és tickets–handle eltérés nem elérhető.')
    st.write('Forrás: ' + p['source']['url'])
    st.write('Eredeti közlés: ' + p['source']['original_text'])
    st.write('Hipotézis: ' + p['hypothesis']); st.write('Magyarázat: ' + p['explanation'])
    timeline = []
    verified_points = [s for s in p['odds'] if available({'source': s['source']})]
    first_prices = verified_points[0]['prices'] if verified_points else {}
    for point in p['odds']:
        if not available({'source': point['source']}):
            continue
        for outcome in p['outcomes']:
            timeline.append({'UTC': point['at'], 'Jelölő': point['kind'], 'Kimenetel': outcome,
                             'Decimális odds': point['prices'][outcome],
                             'Odds változása % az első ponthoz': 100 * (point['prices'][outcome] / first_prices[outcome] - 1),
                             'Marginmentes esély': point['fair_probabilities'][outcome],
                             'Overround': point['overround'], 'Forrás URL': point['source']['url']})
    st.subheader('Odds-idővonal')
    st.dataframe(timeline, hide_index=True)
    if timeline:
        import pandas as pd
        data = pd.DataFrame(timeline)
        data['UTC'] = pd.to_datetime(data['UTC'], utc=True)
        st.line_chart(data.pivot(index='UTC', columns='Kimenetel', values='Decimális odds'))
    else:
        st.info('Ellenőrzött teljes odds-idősor nem elérhető.')
    st.subheader('Meccs előtti információk')
    st.dataframe([{'Típus': n['kind'], 'Tény / feltételezés': n['certainty'], 'Szöveg': n['text'],
                   'Megfigyelés UTC': n['source']['observed_at'], 'Forrás URL': n['source']['url']}
                  for n in p['news'] if available({'source': n['source']})], hide_index=True)


def _results(state):
    st.caption('Az eredmény és utólagos magyarázat új bejegyzés; a korábbi megfigyelést soha nem módosítja. Javítás is új bejegyzés.')
    st.dataframe([e['payload'] for e in state['results']], hide_index=True)
    markets = {}
    for e in state['observations']:
        p = e['payload']; key = (p['sport'], p['fixture_id'], p['market'], p['line'])
        markets[key] = p
    if not markets:
        return
    key = st.selectbox('Értékelendő piac', list(markets), format_func=lambda k:
                       f'{markets[k]["home"]} – {markets[k]["away"]} | {k[2]} | {k[3]}')
    with st.form('market_result'):
        actual = st.text_input('Tényleges kezdés UTC', value=markets[key]['kickoff'])
        ended = st.text_input('Igazolt befejezés UTC')
        score = st.text_input('Végeredmény (szöveges, a piac szabályai szerint)')
        settlement = st.text_area('Elszámolás JSON: kimenetel → win/loss/push/void/half_win/half_loss', value='{}')
        source = st.text_input('Eredmény HTTPS forrása')
        explanation = st.text_area('Utólagos értékelés / javítás indoka')
        confirmed = st.checkbox('Ellenőriztem a befejezést, a tényleges kezdést és a piac elszámolási szabályait')
        save = st.form_submit_button('Utólagos értékelés hozzáfűzése')
    if save:
        try:
            record = dict(zip(('sport', 'fixture_id', 'market', 'line'), key))
            record.update(actual_kickoff=actual, ended_at=ended, score=score,
                          settlement=json.loads(settlement), source_url=source,
                          explanation=explanation, confirmed=confirmed)
        except Exception:
            st.error('Érvénytelen eredmény JSON.'); return
        _save(lambda current: append_result(current, record))


def _research(state, gap, movement, hours, age):
    st.caption('Rögzített szabályok: odds szerinti favorit baseline; legerősebb marginmentes oddsmozgás; legnagyobb handle–tickets eltérés; a kettő azonos oldalon; ugyanez korabeli tényszerű csapathír jelenlétével. A hírváltozat jelenléti szűrő, nem hírértelmező modell.')
    with st.form('market_replay'):
        start = st.text_input('Tesztidőszak kezdete UTC')
        end = st.text_input('Tesztidőszak kizáró vége UTC')
        run = st.form_submit_button('Időrendi kutatási visszajátszás')
    if run:
        try:
            report = backtest(state, test_start=start, test_end=end, gap_threshold=gap,
                              movement_threshold=movement, decision_hours=hours, max_age_hours=age)
            _report(report)
        except Exception:
            st.error('A visszateszt nem futtatható: ellenőrizd az időhatárokat és az adatokat.')
    st.subheader('Előre rögzített kutatási protokoll')
    with st.form('market_protocol'):
        name = st.text_input('Protokoll neve')
        manifest = st.text_area('Előre rögzített mintavételi manifest / teljes meccskör, irodák, piacok és kizárási szabályok')
        start_p = st.text_input('Jövőbeli tesztkezdés UTC')
        end_p = st.text_input('Jövőbeli tesztvég UTC')
        save = st.form_submit_button('Protokoll befagyasztása a jelenlegi küszöbökkel')
    if save:
        _save(lambda current: append_protocol(current, {'name': name, 'manifest': manifest,
              'test_start': start_p, 'test_end': end_p, 'gap_threshold': gap,
              'movement_threshold': movement, 'decision_hours': hours, 'max_age_hours': age}))
    if state['protocols']:
        protocols = {e['entry_hash']: e['payload'] for e in state['protocols']}
        selected = st.selectbox('Mentett protokoll', list(protocols), format_func=lambda h: protocols[h]['name'])
        st.json(protocols[selected])
        if st.button('Befagyasztott protokoll kiértékelése'):
            p = protocols[selected]
            try:
                _report(backtest(state, protocol_hash=selected, **{k: p[k] for k in (
                    'test_start', 'test_end', 'gap_threshold', 'movement_threshold', 'decision_hours', 'max_age_hours')}))
            except Exception:
                st.error('A mentett protokoll nem értékelhető.')


def _report(report):
    for warning in report['warnings']:
        st.warning(warning)
    st.write(f'Korábbi fejlesztési minta: {report["development_n"]}; későbbi tesztminta: {report["test_n"]}.')
    st.dataframe([{'Szabály': rule, **values} for rule, values in report['test'].items()], hide_index=True)
    st.caption('Egységtétes ROI, tényleges rögzített oddsokkal. A CI-k 95%-os fixture-bootstrap intervallumok. A baseline-különbség ugyanazokon a kiválasztott sorokon párosított. A teljes jelentés tartalmazza a margin-, odds-, iroda-, piac- és időkontrollokat, kizárásokat és a korábbi minta adatait.')
    st.download_button('Kutatási jelentés JSON', canonical(report), file_name='market-backtest.json', mime='application/json')


def run():
    st.title('Piaci nyomozó')
    st.caption('Opcionális kutatási napló • kézi / CSV-bevitel • nincs automatikus fogadási tipp')
    if not authorized():
        return
    st.button('Piaci archívum frissítése', key='refresh_market')
    try:
        state, _ = cloud().load()
    except ArchiveMissing:
        st.info('A külön piaci archívum még nem létezik.')
        if st.button('Külön privát piaci archívum létrehozása'):
            try:
                cloud().initialize(); st.rerun()
            except Exception:
                st.error('A létrehozás nem igazolt. Ellenőrizd a privát tárolót és a jogosultságot.')
        return
    except Exception:
        st.error('A piaci archívum nem olvasható. Ellenőrizd a jogosultságot és frissíts; nem nullázzuk a meglévő adatot.')
        return
    st.download_button('Piaci archívum biztonsági mentése', canonical(state), file_name='market-research.json', mime='application/json')
    gap = st.number_input('Handle–tickets küszöb (százalékpont)', min_value=0.0, max_value=100.0, value=10.0)
    movement = st.number_input('Marginmentes oddsmozgás küszöb (százalékpont)', min_value=0.0, max_value=100.0, value=2.0)
    hours = st.number_input('Döntési idő a kezdés előtt (óra)', min_value=0.0, max_value=168.0, value=12.0)
    age = st.number_input('Forrás maximális kora (óra)', min_value=0.1, max_value=720.0, value=24.0)
    view = st.radio('Piaci nézet', ['Megfigyelések', 'Kézi bevitel', 'CSV import', 'Utólagos értékelés', 'Visszateszt'])
    if view == 'Megfigyelések':
        _observations(state, gap, age)
    elif view == 'Kézi bevitel':
        _manual()
    elif view == 'CSV import':
        _import()
    elif view == 'Utólagos értékelés':
        _results(state)
    else:
        _research(state, gap, movement, hours, age)
