"""Streamlit presentation for evidence; existing model stays independent."""
import json
import os
from datetime import date, datetime, timezone
import streamlit as st
from odds_detective import Store, NA, movements, first_observed, collect_odds, collect_betfair, search_news, now

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


def run():
    st.title("🔎 Oddsmozgás-nyomozó")
    st.caption("Ellenőrizhető megfigyelések • 1X2, rendes játékidő • minden időpont UTC")
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
    with st.expander("Új vizsgálat"):
        with st.form("new_investigation"):
            home = st.text_input("Hazai csapat")
            away = st.text_input("Vendégcsapat")
            day = st.date_input("Mérkőzés napja (UTC)", value=date(2026, 10, 22))
            source = st.text_input("Mérkőzés forrás-URL-je")
            if st.form_submit_button("Vizsgálat létrehozása"):
                try:
                    store.add_match(home, away, day.isoformat(), source)
                    st.success("Vizsgálat létrehozva; az esemény még felhasználói ellenőrzésű.")
                except ValueError as e:
                    st.error(str(e))
    matches = store.matches()
    match = st.selectbox("Vizsgált mérkőzés", matches,
        format_func=lambda m: f"{m['home']} – {m['away']} | {m['match_date']}")
    mid = match["id"]
    st.caption(f"Mérkőzés forrása: {match['source']} · Rögzítve: {match['created_at']} · {LABELS[match['verification']]}")
    collect, analysis, news, archive = st.tabs(["Adatgyűjtés", "Idővonal és grafikonok", "Hírek és eredmény", "Adatnapló és export"])
    with collect:
        st.subheader("Hivatalos adatkapcsolatok")
        st.markdown("[The Odds API dokumentáció](https://the-odds-api.com/liveapi/guides/v4/) · "
                    "[Betfair dokumentáció](https://betfair-developer-docs.atlassian.net/wiki/spaces/1smk3cen4v3lu3yomq5qye0ni/pages/2687510/listMarketBook)")
        st.caption("Az ingyenes kvóta és a bajnokság lefedettsége szolgáltatófüggő. Történelmi adatok nem feltétlenül ingyenesek. "
                   "A kulcsokat a Streamlit Secrets-ben add meg; a modul nem írja ki és nem tárolja őket.")
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
