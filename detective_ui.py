"""Streamlit presentation for evidence; existing model stays independent."""
import json
import os
import hashlib
from datetime import datetime, timezone
import streamlit as st
from odds_detective import (Store, NA, movements, first_observed, collect_odds, collect_betfair,
                            search_news, now, list_football_leagues, list_football_events,
                            events_on_date, validate_event_binding, budapest_today, budapest_time,
                            events_on_budapest_date, utc)

LABELS = {"source_checked": "API-forrásból beolvasva", "user_reported": "Felhasználó által megjelölve",
          "unverified": "Nem ellenőrzött", "rejected": "Elutasított"}


def secret(name):
    value = os.environ.get(name)
    if value:
        return value
    try:
        return st.secrets.get(name, "")
    except Exception:
        return ""


def display(records):
    return [{"Típus": r["kind"], "Forrás ideje (UTC)": r["source_time"] or NA,
             "Rögzítés ideje (UTC)": r["collected_at"], "Forrás": r["source"],
             "Állapot": LABELS[r["verification"]], "Adat": json.dumps(r["payload"], ensure_ascii=False)} for r in records]



def open_investigation(mid):
    # Apply on the next run, before either keyed widget is instantiated.
    st.session_state["_pending_investigation"] = mid
    st.rerun()


def daily_search(store):
    st.subheader("Napi mérkőzéskeresés")
    if "daily_match_day" not in st.session_state:
        st.session_state["daily_match_day"] = budapest_today()
    day = st.date_input("Keresési nap (Europe/Budapest)", key="daily_match_day")
    st.caption("A kezdési időket magyar idő szerint mutatjuk. A nap módosítása a már betöltött listát szűri; "
               "API-lekérés csak a betöltés / frissítés gombokkal történik.")
    odds_picker(store, None, day.isoformat())


def odds_picker(store, match, search_day=None):
    st.subheader("Bajnokság és mérkőzés kiválasztása")
    key = secret("ODDS_API_KEY")
    if not key:
        st.warning("Nem elérhető – hiányzik az ODDS_API_KEY a Streamlit Secretsből.")
        return
    # Session-local catalogues only; no secret is stored in widget values or shared caches.
    identity = hashlib.sha256(key.encode()).hexdigest()
    state_key = "_odds_catalogues"
    if st.session_state.get(state_key, {}).get("identity") != identity:
        st.session_state[state_key] = {"identity": identity, "events": {}}
    state = st.session_state[state_key]
    st.caption("1. Töltsd be a bajnokságokat. 2. Válassz bajnokságot, majd töltsd be a mérkőzéseit. "
               "3. Válassz mérkőzést, és kérd le az oddsokat. Nem kell azonosítókat bemásolnod. "
               "A listák lekérése a szolgáltató dokumentációja szerint nem fogyaszt kreditet; az oddslekérés fogyaszthat.")
    if st.button("Bajnokságok betöltése / frissítése", key="load_odds_leagues"):
        try:
            with st.spinner("Bajnokságlista lekérése…"):
                leagues = list_football_leagues(key)
            state["leagues"] = leagues
            state["leagues_at"] = now()
        except Exception:
            state.pop("leagues", None)
            st.error("Nem elérhető – nem sikerült betölteni a bajnokságokat. Ellenőrizd a Secretsben tárolt kulcsot és a kapcsolatot.")
    if "leagues" not in state:
        return
    if not state["leagues"]:
        st.info("Nem elérhető aktív, mérkőzéses labdarúgó-bajnokság az API válaszában.")
        return
    st.caption(f"Bajnokságlista lekérve (UTC): {state['leagues_at']}")
    league = st.selectbox("Bajnokság", state["leagues"], index=None, placeholder="Válassz bajnokságot…",
                          format_func=lambda row: row["title"], key=f"odds_league_{identity[:12]}")
    if league is None:
        return
    sport = league["key"]
    if st.button("Mérkőzések betöltése / frissítése", key="load_odds_events"):
        try:
            with st.spinner("Mérkőzéslista lekérése…"):
                events = list_football_events(key, sport)
            state["events"][sport] = {"rows": events, "at": now()}
        except Exception:
            state["events"].pop(sport, None)
            st.error("Nem elérhető – a mérkőzéslista lekérése sikertelen. Próbáld újra később.")
    catalogue = state["events"].get(sport)
    if catalogue is None:
        return
    st.caption(f"Mérkőzéslista lekérve (UTC): {catalogue['at']}")
    daily = search_day is not None
    day = search_day if daily else match["match_date"]
    zone = "Europe/Budapest" if daily else "UTC"
    events = (events_on_budapest_date(catalogue["rows"], day) if daily
              else events_on_date(catalogue["rows"], day))
    if not events:
        st.info(f"Nem elérhető mérkőzés ebben a bajnokságban a kiválasztott napra ({day}, {zone}). "
                "Ez lehet lefedettségi vagy időbeli korlát. A lista csak élő és közelgő mérkőzéseket tartalmaz; "
                "hiányából nem következik, hogy a mérkőzés nem létezik. Korábbi adatot nem találunk ki.")
        return
    event = st.selectbox("Mérkőzés a kiválasztott napon", events, index=None, placeholder="Válassz mérkőzést…",
        format_func=lambda row: (f"{row['home_team']} – {row['away_team']} | "
            + (budapest_time(row["commence_time"]).strftime("%Y-%m-%d %H:%M %Z") if daily
               else row["commence_time"][:16] + " UTC")),
        key=f"odds_event_{day if daily else match['id']}_{sport}_{identity[:12]}")
    if event is None:
        return
    if daily:
        st.caption("A mentett vizsgálat UTC-napja az API kezdési időpontjából származik; eltérhet a magyar naptári naptól.")
        if st.button("Vizsgálat létrehozása a kiválasztott mérkőzéshez", key="create_daily_investigation"):
            mid = store.add_match(event["home_team"], event["away_team"],
                                  utc(event["commence_time"])[:10],
                                  "https://api.the-odds-api.com/v4/sports/" + sport + "/events/" + event["id"])
            open_investigation(mid)
        return
    confirmed = False
    if (event["home_team"], event["away_team"]) != (match["home"], match["away"]):
        st.warning(f"A vizsgálat: {match['home']} – {match['away']}. Az API-ban a csapatnevek eltérnek; "
                   "csak akkor ments ide adatot, ha valóban ugyanaz a párosítás és a hazai/vendég sorrend is egyezik.")
        confirmed = st.checkbox("Ellenőriztem: ugyanaz a mérkőzés és a hazai/vendég sorrend.",
                                key=f"odds_binding_{match['id']}_{event['id']}")
    if st.button("Kiválasztott mérkőzés 1X2-oddsainak lekérése", key="fetch_selected_odds"):
        try:
            validate_event_binding(event, match, confirmed)
        except ValueError as error:
            st.warning(str(error))
            return
        try:
            with st.spinner("1X2-pillanatkép lekérése…"):
                count = collect_odds(store, match["id"], key, sport, event["id"], event["home_team"], event["away_team"])
            if count:
                st.success(f"Új oddsrekordok: {count}. Az idővonal és az adatnapló frissült.")
            else:
                st.info("Nem elérhető új, teljes 1X2-adat: lehet változatlan vagy hiányzó piac. Az esemény listázása nem garantál EU-oddsokat.")
        except Exception:
            st.error("Nem elérhető – az oddslekérés sikertelen. Ellenőrizd a hozzáférést és a kvótát; "
                     "ha a mérkőzés már befejeződött, a friss listában nem feltétlenül szerepel.")


def run():
    st.title("🔎 Oddsmozgás-nyomozó")
    st.caption("Ellenőrizhető megfigyelések • 1X2, rendes játékidő • napi keresés: Europe/Budapest • mentett bizonyítékok: UTC")
    st.info("Az oddsmozgás nem bizonyít manipulációt. A hírek időbeli közelsége nem igazol ok-okozati kapcsolatot.")
    st.warning("A gyűjtés csak a gomb megnyomásakor vagy külön ütemezett CLI-futtatáskor történik. "
               "A korábbi pillanatképek nem pótolhatók becsléssel. Streamlit Cloudon a helyi adatbázis elveszhet; rendszeresen exportáld.")
    try:
        store = Store()
        store.seed()
    except Exception:
        st.error("Az adatbázis nem elérhető. Ellenőrizd az ODDS_DB_PATH beállítást és az írási jogosultságot.")
        return
    try:
        panel(store)
    finally:
        store.close()


def panel(store):
    # Keep the selected day when Streamlit removes hidden daily-view widgets.
    if "daily_match_day" in st.session_state:
        st.session_state["daily_match_day"] = st.session_state["daily_match_day"]
    if "_pending_investigation" in st.session_state:
        st.session_state["saved_investigation"] = st.session_state.pop("_pending_investigation")
        st.session_state["detective_view"] = "Mentett vizsgálatok / előzmények"
    view = st.radio("Nézet", ["Napi mérkőzéskeresés", "Mentett vizsgálatok / előzmények"],
                    key="detective_view")
    if view == "Napi mérkőzéskeresés":
        daily_search(store)
        return
    st.subheader("Mentett vizsgálatok / előzmények")
    with st.expander("Új vizsgálat"):
        with st.form("new_investigation"):
            home = st.text_input("Hazai csapat")
            away = st.text_input("Vendégcsapat")
            day = st.date_input("Mérkőzés napja (UTC)", value=datetime.now(timezone.utc).date())
            source = st.text_input("Mérkőzés forrás-URL-je")
            if st.form_submit_button("Vizsgálat létrehozása"):
                try:
                    mid = store.add_match(home, away, day.isoformat(), source)
                    open_investigation(mid)
                except ValueError as e:
                    st.error(str(e))
    matches = store.matches()
    if not matches:
        st.info("Még nincs mentett vizsgálat.")
        return
    by_id = {m["id"]: m for m in matches}
    if st.session_state.get("saved_investigation") not in by_id:
        st.session_state["saved_investigation"] = matches[0]["id"]
    selected = st.selectbox("Vizsgált mérkőzés (UTC-nap)", list(by_id), key="saved_investigation",
        format_func=lambda mid: f"{by_id[mid]['home']} – {by_id[mid]['away']} | {by_id[mid]['match_date']}")
    match = by_id[selected]
    mid = match["id"]
    st.caption(f"Mérkőzés forrása: {match['source']} · Rögzítve: {match['created_at']} · {LABELS[match['verification']]}")
    collect, analysis, news, archive = st.tabs(["Adatgyűjtés", "Idővonal és grafikonok", "Hírek és eredmény", "Adatnapló és export"])
    with collect:
        st.subheader("Hivatalos adatkapcsolatok")
        st.markdown("[The Odds API dokumentáció](https://the-odds-api.com/liveapi/guides/v4/) · "
                    "[Betfair dokumentáció](https://betfair-developer-docs.atlassian.net/wiki/spaces/1smk3cen4v3lu3yomq5qye0ni/pages/2687510/listMarketBook)")
        st.caption("Az ingyenes kvóta és a bajnokság lefedettsége szolgáltatófüggő. Történelmi adatok nem feltétlenül ingyenesek. "
                   "A kulcsokat a Streamlit Secrets-ben add meg; a modul nem írja ki és nem tárolja őket.")
        odds_picker(store, match)
        with st.expander("Haladó: azonosítók kézi megadása"):
            with st.form("odds_fetch"):
                sport = st.text_input("Odds API sportkulcs", placeholder="soccer_…")
                event = st.text_input("Odds API eseményazonosító")
                ah = st.text_input("Pontos hazai név az API-ban", value=match["home"])
                aa = st.text_input("Pontos vendégnév az API-ban", value=match["away"])
                if st.form_submit_button("1X2-pillanatkép lekérése"):
                    key = secret("ODDS_API_KEY")
                    if not key:
                        st.warning("Nem elérhető – hiányzik az ODDS_API_KEY.")
                    else:
                        try:
                            count = collect_odds(store, mid, key, sport, event, ah, aa)
                            st.success(f"Új rekordok: {count}") if count else st.info("Nem elérhető új, teljes 1X2-adat; lehet változatlan vagy hiányzó piac.")
                        except Exception:
                            st.error("Nem elérhető – ellenőrizd az eseményt, a csapatneveket, a hozzáférést és a kvótát. Nem mentettünk hibás részadatot.")
        with st.form("betfair_fetch"):
            market = st.text_input("Betfair marketId")
            ids = {o: st.text_input(f"Betfair selectionId – {o}") for o in ("1", "X", "2")}
            currency = st.selectbox("Ellenőrzött Betfair számlapénznem", ["EUR", "GBP", "USD", "HUF", "AUD", "SEK", "DKK", "NOK", "CHF"])
            confirmed = st.checkbox("A Betfair felületén ellenőriztem, hogy a piac és a három selectionId ehhez a mérkőzéshez tartozik.")
            if st.form_submit_button("Párosított forgalom lekérése"):
                key, token = secret("BETFAIR_APP_KEY"), secret("BETFAIR_SESSION_TOKEN")
                if not key or not token:
                    st.warning("Nem elérhető – BETFAIR_APP_KEY és BETFAIR_SESSION_TOKEN szükséges.")
                else:
                    try:
                        count = collect_betfair(store, mid, key, token, market, ids, currency, confirmed)
                        st.success(f"Új forgalmi pillanatképek: {count}")
                    except Exception:
                        st.error("Nem elérhető – ellenőrizd a hozzáférést, piacot, dátumot és a kimenetelek egyezését.")
        with st.expander("Forrásolt JSON-import"):
            st.caption("A rekordok listáját vagy a teljes, innen letöltött exportot fogadjuk. A kézi source_checked jelölés user_reported lesz. "
                       "A rögzítés ideje mindig a tényleges importidő; a korábbi begyűjtési időt nem lehet visszadátumozni.")
            st.code('[{"kind":"odds","source":"https://source.example/record","source_time":"<ISO-8601 időzónával>",'
                    '"verification":"unverified","payload":{"bookmaker":"<iroda>","outcome":"1","odds":null}}]', language="json")
            uploaded = st.file_uploader("JSON-fájl", type=["json"])
            if st.button("Importálás", disabled=uploaded is None):
                try:
                    if uploaded.size > 5_000_000:
                        raise ValueError("Legfeljebb 5 MB importálható egyszerre.")
                    data = json.load(uploaded)
                    if isinstance(data, dict):
                        identity = data.get("match", {})
                        if any(identity.get(k) != match[k] for k in ("home", "away", "match_date")):
                            raise ValueError("Az export másik mérkőzéshez tartozik.")
                        data = data["records"]
                    count = store.ingest(mid, data)
                    st.success(f"Importált új rekordok: {count}")
                except (ValueError, KeyError, TypeError) as e:
                    st.error(f"Sikertelen import: {e}")
    records = store.records(mid)
    with analysis:
        st.caption("Relatív oddsmozgás = (új odds / referenciaodds − 1) × 100. Referencia: előző és első megfigyelés. "
                   "Külön vizsgálat: bármelyik abszolút változás >15%. A jelzés nem fogadási ajánlás.")
        changes = movements(records)
        if changes:
            st.subheader("Elsőként észlelt változás kimenetelenként")
            st.dataframe(first_observed(changes), hide_index=True)
            st.caption("Csak a begyűjtött források között. Az eltérő frissítési ciklusok miatt a tényleges első iroda nem bizonyított. "
                       "Azonos időpontnál minden holtversenyes iroda szerepel; ütköző azonos idejű árak kimaradnak az elemzésből.")
            st.metric("Külön vizsgálandó változások", sum(c["review"] for c in changes))
            st.dataframe(changes, hide_index=True)
        else:
            st.info("Oddsmozgás és elsőként változtató iroda: Nem elérhető – legalább két eltérő, összehasonlítható pillanatkép szükséges.")
        odds = [r for r in records if r["kind"] == "odds" and r["verification"] != "rejected" and r["payload"].get("odds") is not None]
        if odds:
            import pandas as pd
            rows = [{"UTC": pd.to_datetime(r["source_time"], utc=True), "Odds": r["payload"]["odds"],
                     "Sorozat": f"{r['payload']['bookmaker']} · {r['payload']['outcome']} · {r['payload'].get('phase', 'unknown')} · {r['source']}"} for r in odds]
            st.line_chart(pd.DataFrame(rows), x="UTC", y="Odds", color="Sorozat")
        exchange = [r for r in records if r["kind"] == "exchange" and r["verification"] != "rejected"]
        st.subheader("Betfair Exchange párosított forgalom")
        st.caption("Kumulatív piaci és kimenetelenkénti értékek, külön kezelve. Nem fogadási tétek vagy nettó pénzáramlások. "
                   "A hiányzó kimenetelt nem számítjuk ki a teljes forgalomból.")
        if exchange:
            import pandas as pd
            table = []
            plot = []
            for r in exchange:
                p = r["payload"]
                row = {"UTC": r["source_time"], "Piac": p["market_id"], "Pénznem": p["currency"],
                       "Teljes párosított": p.get("total_matched") if p.get("total_matched") is not None else NA,
                       "Késleltetett": p.get("is_delayed") if p.get("is_delayed") is not None else NA,
                       "Forrás": r["source"], "Állapot": LABELS[r["verification"]]}
                for name, value in {"Teljes": p.get("total_matched"), **p.get("runners", {})}.items():
                    if value is not None:
                        plot.append({"UTC": pd.to_datetime(r["source_time"], utc=True), "Forgalom": value,
                            "Sorozat": f"{p['market_id']} · {p['currency']} · {name}"})
                row.update({k: p.get("runners", {}).get(k) if p.get("runners", {}).get(k) is not None else NA for k in ("1", "X", "2")})
                table.append(row)
            st.dataframe(table, hide_index=True)
            if plot:
                st.line_chart(pd.DataFrame(plot), x="UTC", y="Forgalom", color="Sorozat")
        else:
            st.info("Teljes és kimenetelenkénti párosított forgalom: Nem elérhető.")
        st.subheader("Közös idővonal")
        if records:
            st.dataframe(display(records), hide_index=True)
        else:
            st.info("Nem elérhető – még nincs begyűjtött megfigyelés.")
    with news:
        st.caption("A keresési találatok nincsenek tartalmilag ellenőrizve. A közlési idő nem a sérülés vagy esemény bekövetkezési ideje.")
        if st.button("Kapcsolódó hírek keresése (Google News RSS)"):
            try:
                count = store.ingest(mid, search_news(match["home"], match["away"], match["match_date"]))
                st.success(f"Új találatok: {count}")
                records = store.records(mid)
            except Exception:
                st.warning("Nem elérhető – a hírkeresés sikertelen.")
        window = st.slider("Időbeli közelség ablaka (óra)", 1, 72, 24)
        news_rows = [r for r in records if r["kind"] == "news" and r["verification"] != "rejected"]
        for r in news_rows:
            p = r["payload"]
            st.markdown(f"**{p['title']}**")
            st.link_button("Forrás megnyitása", r["source"])
            st.caption(f"Közölve: {r['source_time'] or NA} · Rögzítve: {r['collected_at']} · {LABELS[r['verification']]} · {p['category']}")
            related = []
            if r["source_time"]:
                for c in changes:
                    delta = (datetime.fromisoformat(c["source_time"]) - datetime.fromisoformat(r["source_time"])).total_seconds() / 3600
                    if abs(delta) <= window:
                        related.append({"Iroda": c["bookmaker"], "Kimenetel": c["outcome"], "Mozgás mínusz hír (óra)": round(delta, 2), "Változás %": c["step_pct"]})
            if related:
                st.dataframe(related, hide_index=True)
                st.caption("Pozitív idő: a hír előbb jelent meg. Ez időbeli kapcsolat, az ok nem bizonyított.")
        if not news_rows:
            st.info("Ellenőrizhető sérülés-, eltiltás-, kezdőcsapat- és rotációs hír: Nem elérhető.")
        with st.form("manual_evidence"):
            kind = st.selectbox("Rögzítés típusa", ["news", "result"])
            title = st.text_input("Hírcím (hírnél)")
            category = st.selectbox("Hírkategória", ["injury", "suspension", "lineup", "rotation", "other"])
            hg = st.number_input("Hazai gól (eredménynél, 90 perc)", min_value=0, value=None, step=1)
            ag = st.number_input("Vendéggól (eredménynél, 90 perc)", min_value=0, value=None, step=1)
            src = st.text_input("Közlés pontos forrás-URL-je")
            stamp = st.text_input("Közlés ideje (ISO-8601 időzónával)", placeholder="YYYY-MM-DDTHH:MM:SS+00:00")
            checked = st.checkbox("A forrást személyesen ellenőriztem")
            if st.form_submit_button("Forrásolt rekord mentése"):
                payload = {"title": title, "category": category} if kind == "news" else {"home_goals": hg, "away_goals": ag, "period": "FT_90"}
                try:
                    store.ingest(mid, [{"kind": kind, "source": src, "source_time": stamp or None,
                        "verification": "user_reported" if checked else "unverified", "payload": payload}])
                    st.success("Rekord mentve. A kézi ellenőrzési állítás nem automatikus hitelesítés.")
                    records = store.records(mid)
                except (ValueError, TypeError) as e:
                    st.error(str(e))
        results = [r for r in records if r["kind"] == "result"]
        if results:
            st.subheader("Rögzített végeredmények – eltérés esetén további ellenőrzés szükséges")
            st.dataframe(display(results), hide_index=True)
        else:
            st.info("Végeredmény: Nem elérhető.")
    with archive:
        st.caption("As-of bemenet: csak a határidőig már rögzített és forrásidővel is rendelkező rekordok. "
                   "A végeredmény külön címke; nincs automatikus ok- vagy nyereségállítás.")
        cutoff = st.text_input("Visszateszt határideje (ISO-8601, időzónával; üres = teljes napló)")
        try:
            selected = store.records(mid, cutoff or None)
            pack = {"schema_version": 1, "exported_at": now(), "match": match, "cutoff": cutoff or None,
                    "records": selected, "features": [r for r in selected if r["kind"] != "result" and r["verification"] != "rejected"],
                    "result_labels": [r for r in records if r["kind"] == "result"]}
            st.download_button("JSON-adatbázis exportja", json.dumps(pack, ensure_ascii=False, indent=2), file_name=f"{mid}-evidence.json", mime="application/json")
            if selected:
                st.dataframe(display(selected), hide_index=True)
        except ValueError as e:
            st.error(str(e))


