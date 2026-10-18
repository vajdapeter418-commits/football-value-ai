import csv
import io
import math
from datetime import datetime
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


def goltabla(gh, gv):
    if not all(
        math.isfinite(x) and 0 < x <= 20
        for x in (gh, gv)
    ):
        raise ValueError("A gólátlag kívül esik a modell tartományán.")

    ph = [math.exp(-gh)]
    pv = [math.exp(-gv)]

    for k in range(1, 101):
        ph.append(ph[-1] * gh / k)
        pv.append(pv[-1] * gv / k)

    return [
        (h, v, p * q)
        for h, p in enumerate(ph)
        for v, q in enumerate(pv)
    ]


def becsles(meccsek, hazai, vendeg):
    lh = sum(m[2] for m in meccsek) / len(meccsek)
    lv = sum(m[3] for m in meccsek) / len(meccsek)

    h = [m for m in meccsek if m[0] == hazai]
    v = [m for m in meccsek if m[1] == vendeg]

    if not h or not v or min(lh, lv) <= 0:
        raise ValueError("Nincs elég megfelelő csapatadat.")

    hf = (sum(m[2] for m in h) + 5 * lh) / (len(h) + 5)
    hc = (sum(m[3] for m in h) + 5 * lv) / (len(h) + 5)
    vf = (sum(m[3] for m in v) + 5 * lv) / (len(v) + 5)
    vc = (sum(m[2] for m in v) + 5 * lh) / (len(v) + 5)

    gh = hf * vc / lh
    gv = vf * hc / lv

    p = [0.0, 0.0, 0.0]

    for a, b, esely in goltabla(gh, gv):
        index = 0 if a > b else 1 if a == b else 2
        p[index] += esely

    return (
        [x / sum(p) for x in p],
        gh,
        gv,
        len(h),
        len(v),
    )


def pontos_eredmenyek(gh, gv):
    tabla = sorted(
        goltabla(gh, gv),
        key=lambda r: (-r[2], r[0], r[1]),
    )

    return tabla[:5]


def visszateszt(meccsek):
    sorok = []
    kihagyott = 0

    for nap in sorted({m[4] for m in meccsek}):
        mult = [m for m in meccsek if m[4] < nap]
        mai = [m for m in meccsek if m[4] == nap]

        if len(mult) < 60:
            kihagyott += len(mai)
            continue

        alap = [1.0, 1.0, 1.0]

        for m in mult:
            index = 0 if m[2] > m[3] else 1 if m[2] == m[3] else 2
            alap[index] += 1

        alap = [x / (len(mult) + 3) for x in alap]

        for m in mai:
            hazai_db = sum(x[0] == m[0] for x in mult)
            vendeg_db = sum(x[1] == m[1] for x in mult)

            if hazai_db < 3 or vendeg_db < 3:
                kihagyott += 1
                continue

            try:
                p, *_ = becsles(mult, m[0], m[1])
            except ValueError:
                kihagyott += 1
                continue

            y = (
                0 if m[2] > m[3]
                else 1 if m[2] == m[3]
                else 2
            )

            cel = [int(i == y) for i in range(3)]

            sorok.append((
                sum((a - b) ** 2 for a, b in zip(p, cel)),
                sum((a - b) ** 2 for a, b in zip(alap, cel)),
            ))

    return sorok, kihagyott


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
    st.set_page_config(
        page_title="Football Value AI",
        page_icon="⚽",
        layout="centered",
    )

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
            "A kiválasztott idény összes elérhető "
            "eredményét használjuk."
        )

        with st.form("elemzes"):
            hazai = st.selectbox("Hazai csapat", csapatok)
            vendeg = st.selectbox(
                "Vendégcsapat", csapatok, index=1
            )

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
                    p, gh, gv, nh, nv = becsles(
                        meccsek, hazai, vendeg
                    )

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
                    "a pontos eredmények pontosságát "
                    "külön még nem teszteltük."
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

                forma_mutatasa(meccsek, hazai)
                forma_mutatasa(meccsek, vendeg)

    with teszt:
        st.subheader("Időrendi 1X2 visszateszt")

        st.write(
            "Minden meccsnél csak a korábbi napok "
            "eredményeit használjuk. Kezdeti feltétel: "
            "60 ligameccs és legalább 3 megfelelő hazai, "
            "illetve idegenbeli csapatmeccs."
        )

        if st.button(
            "Visszateszt indítása",
            use_container_width=True,
        ):
            with st.spinner("Visszateszt…"):
                sorok, kihagyott = visszateszt(meccsek)

            st.metric("Tesztelt mérkőzések", len(sorok))
            st.caption(
                f"Kihagyott mérkőzések: {kihagyott}"
            )

            if sorok:
                modell = sum(r[0] for r in sorok) / len(sorok)
                alap = sum(r[1] for r in sorok) / len(sorok)

                st.metric(
                    "Modell Brier-pontszáma",
                    f"{modell:.3f}",
                )
                st.metric(
                    "Ligaátlagos becslés Brier-pontszáma",
                    f"{alap:.3f}",
                )

                st.caption(
                    "Kisebb érték = jobb. "
                    "A háromkimeneteles Brier-pontszám "
                    "0 és 2 közötti."
                )

                if modell < alap:
                    st.write(
                        "A modell ezen a mintán "
                        "jobb volt a ligaátlagnál."
                    )
                else:
                    st.write(
                        "A modell ezen a mintán "
                        "nem volt jobb a ligaátlagnál."
                    )

                st.write(
                    "A referencia a korábbi napok "
                    "eredményarányait használja, "
                    "kimenetelenként egy kezdeti mintával. "
                    "Mindkét módszert ugyanazokon "
                    "a meccseken mérjük."
                )

            else:
                st.info(
                    "Még nincs elég adat. "
                    "Próbáld a 2025/26-os idényt."
                )

            st.warning(
                "Ez az 1X2 esélyek tesztje. "
                "Nem a pontos eredményeket és nem "
                "a fogadási nyereséget vizsgálja."
            )

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
            "Nem kezeljük külön az ellenfelek erősségét, "
            "a sérüléseket és a kezdőcsapatokat. "
            "A mérkőzéselemzés teljes idényadatot használ; "
            "korábbi meccsre nem előzetes teszt. "
            "A visszateszt időrendben számol. "
            "Nincs garantált nyereség."
        )

    st.caption(
        "Adatforrás: Football-Data.co.uk • "
        "Legfeljebb 24 órás gyorsítótár."
    )


if __name__ == "__main__":
    main()
