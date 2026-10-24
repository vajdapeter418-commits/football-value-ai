import csv
import io
import math
from datetime import datetime, time, timezone
from urllib.request import Request, urlopen

import streamlit as st


def feldolgozas(raw):
    olvaso = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
    mezok = {"Div", "Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG"}

    if not mezok.issubset(olvaso.fieldnames or []):
        raise ValueError("Hiányzó oszlopok az adatfájlban.")

    meccsek = []

    for s in olvaso:
        if s["Div"] != "E0" or not s["FTHG"] or not s["FTAG"]:
            continue

        h, v = int(s["FTHG"]), int(s["FTAG"])

        if min(h, v) < 0:
            raise ValueError("Érvénytelen gólszám.")

        datum = datetime.strptime(s["Date"], "%d/%m/%Y").date()

        meccsek.append(
            (s["HomeTeam"], s["AwayTeam"], h, v, datum)
        )

    if len(meccsek) < 20:
        raise ValueError("Legalább 20 befejezett mérkőzés szükséges.")

    return meccsek


from poisson_model import goltabla, becsles, pontos_eredmenyek


def visszateszt(meccsek):
    """PR #1 top-score metrics, retaining its three-value return contract."""
    from correct_score_backtest import backtest
    from asof_features import adapt_tuples
    report = backtest(adapt_tuples(meccsek))
    scores, exact = [], []
    for row in report['rows']:
        past = [m for m in meccsek if str(m[4]) < row['date']]
        prior = [1.0, 1.0, 1.0]
        for m in past:
            prior[0 if m[2]>m[3] else 1 if m[2]==m[3] else 2] += 1
        prior = [v/(len(past)+3) for v in prior]
        h,a = row['label']
        y = 0 if h>a else 1 if h==a else 2
        score = row['metrics']['baseline']
        scores.append((score['brier'],sum((p-int(i==y))**2 for i,p in enumerate(prior))))
        top = row['forecasts']['baseline']['candidate']['top5']
        exact.append({'top1':score['top1'],'top5':score['top5'],
                      'top1_becsult':score['estimated_top1'],'top5_becsult':score['estimated_top5'],
                      'valos_eredmeny':f'{h}–{a}','elso_tipp':f'{top[0][0]}–{top[0][1]}'})
    return scores, sum(report['skipped'].values()), exact


def forma_mutatasa(meccsek, csapat):
    utolso = sorted(
        [m for m in meccsek if csapat in m[:2]],
        key=lambda m: m[4],
        reverse=True,
    )[:5]

    sorok = []

    for h, v, hg, vg, datum in utolso:
        otthon = h == csapat
        lott, kapott = (hg, vg) if otthon else (vg, hg)

        sorok.append({
            "Dátum": datum.strftime("%Y.%m.%d."),
            "Ellenfél": v if otthon else h,
            "Helyszín": "Hazai" if otthon else "Idegenben",
            "Lőtt": lott,
            "Kapott": kapott,
            "Eredmény": (
                "GY" if lott > kapott
                else "D" if lott == kapott
                else "V"
            ),
        })

    st.subheader(f"{csapat} – legutóbbi {len(sorok)} meccs")

    jelek = [r["Eredmény"] for r in sorok]

    st.write(" → ".join(jelek))
    st.caption(
        "Balról a legfrissebb. "
        "GY = győzelem, D = döntetlen, V = vereség."
    )

    st.write(
        f"Győzelem: {jelek.count('GY')} · "
        f"Döntetlen: {jelek.count('D')} · "
        f"Vereség: {jelek.count('V')}"
    )

    st.write(
        f"Gólok: {sum(r['Lőtt'] for r in sorok)} lőtt / "
        f"{sum(r['Kapott'] for r in sorok)} kapott"
    )

    st.dataframe(
        sorok,
        hide_index=True,
        use_container_width=True,
    )


@st.cache_data(ttl=86400)
def letoltes(kod):
    url = f"https://www.football-data.co.uk/mmz4281/{kod}/E0.csv"

    keres = Request(
        url,
        headers={"User-Agent": "FootballValueAI/1.0"},
    )

    with urlopen(keres, timeout=30) as valasz:
        return feldolgozas(valasz.read())


def main():
    st.title("⚽ Football Value AI")

    ideny = st.selectbox("Idény", ["2026/27", "2025/26"])
    kod = {"2026/27": "2627", "2025/26": "2526"}[ideny]

    try:
        with st.spinner("Adatok betöltése…"):
            meccsek = letoltes(kod)

    except Exception as hiba:
        st.error(
            "Az adatbetöltés sikertelen. Próbáld a másik idényt."
        )

        with st.expander("Hiba részletei"):
            st.text(str(hiba))

        st.stop()

    csapatok = sorted(
        {m[0] for m in meccsek}
        | {m[1] for m in meccsek}
    )

    st.caption(
        f"{len(meccsek)} meccs • "
        f"{min(m[4] for m in meccsek):%Y.%m.%d.}–"
        f"{max(m[4] for m in meccsek):%Y.%m.%d.}"
    )

    elemzes, teszt = st.tabs(
        ["Mérkőzéselemzés", "Visszateszt"]
    )

    with elemzes:
        st.info(
            "Statisztikai becslés, nem élő adat. "
            "Csak a célmeccs és a cutoff napja előtti eredményeket használjuk. "
            "Retrospektív eredmény-visszajátszás, korabeli adatarchívum nélkül."
        )

        with st.form("elemzes"):
            hazai = st.selectbox("Hazai csapat", csapatok)
            vendeg = st.selectbox(
                "Vendégcsapat", csapatok, index=1
            )

            target_date = st.date_input("Célmérkőzés dátuma (forrás szerinti nap)")
            cutoff_date = st.date_input("Előrejelzési cutoff dátuma (Europe/Budapest)")
            cutoff_time = st.time_input("Cutoff időpontja (Europe/Budapest)", value=time(12, 0))
            mode = st.selectbox("Modell", ["baseline", "core"],
                                format_func=lambda m: "Eredeti baseline" if m == "baseline" else "Kísérleti csapaterősség")
            st.caption("A CSV kezdési és archiválási idő nélkül csak napalapú replayre alkalmas. "
                       "Az extra blokkok inaktívak; nincs xG-/stílus-/játékosarchívum.")
            st.caption(
                "Az aktuális, rendes játékidős "
                "1X2 oddsokat add meg."
            )

            oh = st.number_input(
                "Hazai odds",
                min_value=1.01,
                value=2.30,
                step=0.01,
            )
            od = st.number_input(
                "Döntetlen odds",
                min_value=1.01,
                value=3.20,
                step=0.01,
            )
            ov = st.number_input(
                "Vendég odds",
                min_value=1.01,
                value=3.00,
                step=0.01,
            )

            indul = st.form_submit_button(
                "Elemzés indítása",
                use_container_width=True,
            )

        if indul:
            if hazai == vendeg:
                st.error("Válassz két különböző csapatot.")

            else:
                try:
                    from asof_features import Request as PredictionRequest, adapt_tuples, snapshot, budapest
                    from team_strength import Config, predict
                    from zoneinfo import ZoneInfo
                    cutoff = datetime.combine(cutoff_date, cutoff_time, tzinfo=ZoneInfo("Europe/Budapest"))
                    request = PredictionRequest(hazai, vendeg, 'E0', ideny, target_date, cutoff)
                    snap = snapshot(adapt_tuples(meccsek, season=ideny), request)
                    prediction = predict(snap, hazai, vendeg, Config(mode=mode))
                    p = prediction.candidate.one_x_two
                    gh, gv = prediction.candidate.lambdas
                    _, nh, nv = prediction.raw_counts
                    snapshot_matches = [m.legacy() for m in snap.matches]

                except ValueError as hiba:
                    st.error(str(hiba))
                    st.stop()

                if nh < 10 or nv < 10:
                    st.warning(
                        "⚠️ Kevés adat — bizonytalan becslés. "
                        f"{nh} hazai és {nv} idegenbeli "
                        "meccs alapján számolunk. "
                        "A pozitív hozam nem igazolt "
                        "fogadási előny."
                    )

                st.caption(
                    "A tízmeccses határ óvatossági szabály; "
                    "elérése nem bizonyít megbízhatóságot."
                )

                st.subheader(f"{hazai} – {vendeg}")
                st.caption(f"Cutoff: {budapest(cutoff)} · {prediction.policy}")
                st.caption(f"Snapshot: {prediction.snapshot_hash} · Modell: {prediction.model_version} "
                           f"· Config: {prediction.config_hash}")
                st.dataframe([
                    {"Modell": label, "λ hazai": result.lambdas[0], "λ vendég": result.lambdas[1],
                     "1 (%)": 100*result.one_x_two[0], "X (%)": 100*result.one_x_two[1],
                     "2 (%)": 100*result.one_x_two[2], "Levágott faroktömeg": result.tail_mass}
                    for label, result in (("Baseline", prediction.baseline), ("Kiválasztott", prediction.candidate))
                ], hide_index=True, use_container_width=True)
                st.dataframe([
                    {"Modell": label, "Eredmény": f"{h}–{a}", "Esély (%)": 100*q, "Fair odds": 1/q}
                    for label, result in (("Baseline", prediction.baseline), ("Kiválasztott", prediction.candidate))
                    for h,a,q in result.top5
                ], hide_index=True, use_container_width=True)
                st.write({"Nyers core λ": prediction.core_lambdas, "Extrák loghatása": prediction.extra_delta,
                          "Nyers korrekció": prediction.raw_ratios, "Alkalmazott korrekció": prediction.applied_ratios,
                          "Korlát aktív": prediction.clipped, "Mintaszám": prediction.raw_counts,
                          "Effektív mintaszám": prediction.effective_counts,
                          "Aktív jelzések": prediction.active_signals, "Hiányzó jelzések": prediction.missing_signals})
                if prediction.fallback_reason:
                    st.warning(f"Baseline fallback: {prediction.fallback_reason}")
                if prediction.team_parameters:
                    st.caption("a > 0: erősebb támadás; d > 0: több engedett gól, gyengébb védekezés.")
                    st.dataframe([{"Csapat": t, "Hazai a": ah, "Hazai d": dh, "Vendég a": aa, "Vendég d": da}
                                  for t,ah,dh,aa,da in prediction.team_parameters if t in (hazai,vendeg)],
                                 hide_index=True, use_container_width=True)

                st.write(
                    f"Becsült gólátlag: **{gh:.2f} – {gv:.2f}**"
                )

                st.caption(
                    f"{nh} hazai és {nv} idegenbeli meccs alapján."
                )

                st.subheader("Legvalószínűbb pontos eredmények")

                top = pontos_eredmenyek(gh, gv)

                st.caption(
                    "Az eredmények sorrendje: hazai–vendég. "
                    "Rendes játékidő, hosszabbítás nélkül."
                )

                st.dataframe(
                    [
                        {
                            "Eredmény": f"{h}–{v}",
                            "Esély (%)": round(q * 100, 2),
                            "Fair odds": round(1 / q, 2),
                        }
                        for h, v, q in top
                    ],
                    hide_index=True,
                    use_container_width=True,
                )

                lefedes = sum(q for _, _, q in top) * 100

                st.write(
                    "Az öt eredmény együttes becsült esélye: "
                    f"**{lefedes:.1f}%**. "
                    "Minden más eredmény együtt: "
                    f"**{100 - lefedes:.1f}%**."
                )

                st.warning(
                    "A legvalószínűbb eredmény sem biztos tipp. "
                    "Ezek a gólmodell becslései; "
                    "a visszateszt a külön fülön, kattintásra indul."
                )

                st.subheader("1X2 becslés")

                nevek = [
                    "Hazai győzelem",
                    "Döntetlen",
                    "Vendéggyőzelem",
                ]

                for nev, esely, odds in zip(
                    nevek, p, [oh, od, ov]
                ):
                    with st.container(border=True):
                        st.subheader(nev)

                        st.metric(
                            "Becsült esély",
                            f"{esely * 100:.1f}%",
                        )

                        st.write(
                            f"Fair odds: **{1 / esely:.2f}**"
                        )

                        st.metric(
                            "Becsült várható hozam",
                            f"{(esely * odds - 1) * 100:+.1f}%",
                        )

                st.caption(
                    "Az alábbi forma tájékoztatás; "
                    "külön nem módosítja a becslést."
                )

                forma_mutatasa(snapshot_matches, hazai)
                forma_mutatasa(snapshot_matches, vendeg)

    with teszt:
        st.subheader("Párosított időrendi pontoseredmény-visszateszt")
        st.caption("60 korábbi ligameccs, csapatonként 3 helyszín szerinti meccs; napalapú 60/20/20 osztás. "
                   "A bootstrap 2000 napcsoportos újramintát használ (seed=42). Nem profitmérés.")
        if st.button("Visszateszt indítása", use_container_width=True):
            from correct_score_backtest import backtest
            from asof_features import adapt_tuples
            with st.spinner("Időrendi illesztés és bootstrap…"):
                report = backtest(adapt_tuples(meccsek, season=ideny))
            st.metric("Tesztelt mérkőzések", report['evaluated'])
            st.write({k:v for k,v in report.items() if k not in ('rows','summary')})
            for part, summary in report['summary'].items():
                st.subheader(part)
                st.dataframe([{"Modell": k, **v} for k,v in summary.items()],
                             hide_index=True, use_container_width=True)
            if report['evidence'] == 'insufficient':
                st.warning("Elégtelen bizonyíték: 200-nál kevesebb érintetlen tesztmeccs vagy hiányzó extra archívum.")
            st.download_button("Teljes JSON-jelentés", __import__('json').dumps(report, ensure_ascii=False, indent=2),
                               "backtest-report.json", "application/json")

    with st.expander("Módszer és korlátok"):
        st.write(
            "Ligaátlaghoz viszonyított gólátlagokat "
            "használunk, öt ligaátlagos mintameccses "
            "simítással. A két csapat góljait független "
            "Poisson-eloszlással közelítjük. "
            "A fair odds a becsült esély reciproka, "
            "nem fogadóirodai ajánlat."
        )

        st.write(
            "A kísérleti core ellenfélerősséget és 90 napos frissességet illeszt (ridge=5). "
            "A teljes korrekció a baseline-hoz képest ±25%-ra korlátozott. "
            "A sérülések és kezdők adatarchívum nélkül inaktívak. "
            "A visszateszt időrendben számol. "
            "Nincs garantált nyereség."
        )

    st.caption(
        "Adatforrás: Football-Data.co.uk • "
        "Legfeljebb 24 órás gyorsítótár."
    )


# FPL CSAPATHÍREK – a meglévő fájl legvégére másolandó

   # FPL CSAPATHÍREK – mobilos játékoskártyák
import json as fpl_json
from datetime import datetime, time, timezone as fpl_ido, timezone as fpl_zona


@st.cache_data(ttl=1800)
def fpl_betoltes():
    keres = Request(
        "https://fantasy.premierleague.com/api/bootstrap-static/",
        headers={"User-Agent": "FootballValueAI/1.0"},
    )

    with urlopen(keres, timeout=25) as valasz:
        adat = fpl_json.load(valasz)

    if (
        not isinstance(adat.get("teams"), list)
        or not isinstance(adat.get("elements"), list)
    ):
        raise ValueError("Az FPL-adatforrás formátuma megváltozott.")

    if not adat["teams"] or not adat["elements"]:
        raise ValueError("Az FPL-adatforrás üres.")

    ido = fpl_ido.now(fpl_zona.utc).strftime(
        "%Y.%m.%d. %H:%M UTC"
    )

    return adat, ido


def fpl_kategoria(statusz, hir):
    szoveg = hir.casefold()

    tavozas = (
        "has joined",
        "has left",
        "has departed",
        "has been loaned",
        "has moved to",
        "contract terminated",
        "contract has expired",
    )

    if any(minta in szoveg for minta in tavozas):
        return "Távozás / kölcsönadás"

    if statusz == "s":
        return "Eltiltás"

    if statusz == "i":
        return "Sérülés"

    if statusz == "d":
        return "Kérdéses szereplés"

    return "Egyéb / ellenőrizendő"


def fpl_hirek(adat, csapat_id):
    statuszok = {
        "a": "Elérhetőként jelölve",
        "d": "Kérdéses",
        "i": "Sérültként jelölve",
        "s": "Eltiltottként jelölve",
        "u": "Nem elérhető",
        "n": "Nem elérhetőként jelölve",
    }

    sorok = []

    for j in adat["elements"]:
        if j.get("team") != csapat_id:
            continue

        statusz = j.get("status")
        hir = (j.get("news") or "").strip()
        esely = j.get("chance_of_playing_next_round")

        if (
            statusz == "a"
            and not hir
            and (esely is None or esely == 100)
        ):
            continue

        nev = " ".join(
            filter(
                None,
                [j.get("first_name"), j.get("second_name")],
            )
        )

        sorok.append({
            "nev": nev or j.get("web_name", "Ismeretlen"),
            "statusz": statuszok.get(
                statusz, "Ismeretlen státusz"
            ),
            "kategoria": fpl_kategoria(statusz, hir),
            "esely": esely,
            "hir": hir or "Nincs szöveges információ.",
            "hir_ideje": j.get("news_added") or "Nem közölt",
        })

    return sorted(sorok, key=lambda r: r["nev"])


def fpl_kartyak(sorok, cid):
    if not sorok:
        st.info(
            "Nincs megjeleníthető FPL-hír vagy figyelmeztetés. "
            "Ez nem igazolja, hogy minden játékos bevethető."
        )
        return

    kategoriak = [
        "Sérülés",
        "Eltiltás",
        "Kérdéses szereplés",
        "Távozás / kölcsönadás",
        "Egyéb / ellenőrizendő",
    ]

    for kategoria in kategoriak:
        darab = sum(
            r["kategoria"] == kategoria
            for r in sorok
        )
        st.write(f"{kategoria}: **{darab}**")

    valasztott = st.multiselect(
        "Megjelenített csoportok",
        kategoriak,
        default=kategoriak,
        key=f"fpl_csoportok_{cid}",
    )

    lathato = [
        r for r in sorok
        if r["kategoria"] in valasztott
    ]

    if not lathato:
        st.info(
            "A kiválasztott csoportokban nincs "
            "megjeleníthető játékos."
        )

    for kategoria in kategoriak:
        csoport = [
            r for r in lathato
            if r["kategoria"] == kategoria
        ]

        if not csoport:
            continue

        st.markdown(f"#### {kategoria}")

        for r in csoport:
            with st.container(border=True):
                st.text(r["nev"])
                st.write(f"FPL-státusz: {r['statusz']}")

                esely = r["esely"]

                if esely is None:
                    st.caption(
                        "FPL-játékesély: nincs közölt adat."
                    )
                else:
                    st.caption(
                        "FPL-játékesély a következő fordulóra: "
                        f"{esely}%"
                    )

                st.text(r["hir"])

                st.caption(
                    "A hír időpontja, a forrás szerint: "
                    f"{r['hir_ideje']}"
                )


def fpl_panel():
    st.divider()
    st.header("Csapathírek és kézzel rögzített kezdők")

    st.info(
        "Ez a panel az FPL jelenlegi adatait mutatja, "
        "a fenti idényválasztótól függetlenül. "
        "A csapatokat itt külön válaszd ki. "
        "Az információk nem módosítják a modell esélyeit."
    )

    if st.button(
        "FPL-csapathírek betöltése",
        key="fpl_inditas",
    ):
        st.session_state["fpl_panel_aktiv"] = True

    if not st.session_state.get("fpl_panel_aktiv"):
        return

    try:
        with st.spinner("FPL-adatok betöltése…"):
            adat, ido = fpl_betoltes()

    except Exception as hiba:
        st.error(
            "Az FPL-adatok most nem tölthetők be. "
            "A futballelemzés ettől még használható."
        )

        with st.expander("FPL-hiba részletei"):
            st.text(f"{type(hiba).__name__}: {hiba}")

        return

    st.caption(
        f"Utolsó sikeres lekérés: {ido} · "
        "Legfeljebb 30 perces gyorsítótár."
    )

    st.warning(
        "Az FPL-jelzés nem teljes sérüléslista és "
        "nem hivatalos kezdőcsapat. A játékesély az "
        "FPL következő fordulójára vonatkozik, "
        "nem a kezdés esélye. A hiányzó adat "
        "nem jelent biztos játékot."
    )

    st.caption(
        "A csoportosítás az FPL-státusz és egyes angol "
        "hírfordulatok alapján készül. Az eredeti hírt "
        "mindig megmutatjuk. A hír időpontja nem feltétlenül "
        "az állapot utolsó ellenőrzése."
    )

    csapatok = {
        c["name"]: c["id"]
        for c in adat["teams"]
    }
    nevek = sorted(csapatok)

    hazai = st.selectbox(
        "Csapathírek – hazai",
        nevek,
        key="fpl_hazai",
    )

    vendeg = st.selectbox(
        "Csapathírek – vendég",
        nevek,
        index=min(1, len(nevek) - 1),
        key="fpl_vendeg",
    )

    if hazai == vendeg:
        st.warning(
            "A csapathírekhez két különböző csapatot válassz."
        )
        return

    datum = st.date_input(
        "A vizsgált mérkőzés dátuma",
        key="fpl_meccsnap",
    )

    st.caption(
        "A kezdőket csapatonként és dátumonként külön "
        "kezeljük. Csak ebben a böngészőmunkamenetben "
        "maradnak meg; nem készül tartós mentés."
    )

    for nev in [hazai, vendeg]:
        cid = csapatok[nev]

        st.subheader(nev)
        sorok = fpl_hirek(adat, cid)
        fpl_kartyak(sorok, cid)

        azonosito = f"{cid}_{datum.isoformat()}"

        with st.expander(
            f"{nev} – hivatalos kezdő kézi rögzítése"
        ):
            st.caption(
                "Csak a klub vagy a versenyszervező "
                "közzététele után írd be. Játékosonként "
                "egy sor, összesen 11 különböző név."
            )

            szoveg = st.text_area(
                "Kezdő játékosok",
                key=f"fpl_xi_{azonosito}",
            )

            forras = st.text_input(
                "A közlés forrásának webcíme",
                key=f"fpl_forras_{azonosito}",
            )

            megerositve = st.checkbox(
                "Ellenőriztem a hivatalos közlést "
                "ehhez a meccshez.",
                key=f"fpl_ok_{azonosito}",
            )

            jatekosok = [
                s.strip()
                for s in szoveg.splitlines()
                if s.strip()
            ]

            if megerositve:
                if (
                    len(jatekosok) != 11
                    or len({j.casefold() for j in jatekosok}) != 11
                ):
                    st.warning(
                        "Pontosan 11 különböző játékost "
                        "adj meg, külön sorokban."
                    )

                elif not forras.strip().startswith(
                    ("https://", "http://")
                ):
                    st.warning(
                        "Add meg a hivatalos közlés webcímét is."
                    )

                else:
                    st.success(
                        "Felhasználó által hivatalos forrásból "
                        "ellenőrzöttként megjelölve. "
                        "Az alkalmazás a közlést nem hitelesítette."
                    )

            elif jatekosok:
                st.info(
                    "Kézi jegyzet – a hivatalos közlés "
                    "még nincs visszaigazolva."
                )

    st.caption(
        "Forrás: Fantasy Premier League. "
        "A hírek az eredeti nyelven jelennek meg."
    )


if __name__ == "__main__":
    st.set_page_config(page_title="Football Value AI", page_icon="⚽", layout="centered")
    oldal = st.sidebar.radio("Funkció", ["Mérkőzéselemzés és FPL", "Oddsmozgás-nyomozó", "API-kapcsolat ellenőrzése"])
    if oldal == "Oddsmozgás-nyomozó":
        from detective_ui import run
        run()
    elif oldal == "API-kapcsolat ellenőrzése":
        from api_connection_ui import run
        run()
    else:
        main()
        fpl_panel()




