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

    for sor in olvaso:
        if sor["Div"] != "E0" or not sor["FTHG"] or not sor["FTAG"]:
            continue

        datum = datetime.strptime(sor["Date"], "%d/%m/%Y").date()
        h, v = int(sor["FTHG"]), int(sor["FTAG"])

        if min(h, v) < 0:
            raise ValueError("Érvénytelen gólszám.")

        meccsek.append(
            (sor["HomeTeam"], sor["AwayTeam"], h, v, datum)
        )

    if len(meccsek) < 20:
        raise ValueError("Legalább 20 befejezett mérkőzés szükséges.")

    return meccsek


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

    eselyek = [0.0, 0.0, 0.0]

    for i, p in enumerate(ph):
        for j, q in enumerate(pv):
            index = 0 if i > j else 1 if i == j else 2
            eselyek[index] += p * q

    osszeg = sum(eselyek)

    return (
        [p / osszeg for p in eselyek],
        gh,
        gv,
        len(h),
        len(v),
    )


def visszateszt(meccsek):
    eredmenyek = []
    kihagyott = 0
    napok = sorted({m[4] for m in meccsek})

    for nap in napok:
        mult = [m for m in meccsek if m[4] < nap]
        mai = [m for m in meccsek if m[4] == nap]

        if len(mult) < 60:
            kihagyott += len(mai)
            continue

        alap = [1.0, 1.0, 1.0]

        for m in mult:
            index = 0 if m[2] > m[3] else 1 if m[2] == m[3] else 2
            alap[index] += 1

        alap = [p / (len(mult) + 3) for p in alap]

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

            tenyleges = (
                0 if m[2] > m[3]
                else 1 if m[2] == m[3]
                else 2
            )

            cel = [int(i == tenyleges) for i in range(3)]

            modell = sum(
                (a - b) ** 2 for a, b in zip(p, cel)
            )
            referencia = sum(
                (a - b) ** 2 for a, b in zip(alap, cel)
            )

            eredmenyek.append((nap, modell, referencia))

    return eredmenyek, kihagyott


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
            "Statisztikai becslés, nem élő adat. Az egész "
            "kiválasztott idény elérhető eredményeit használja."
        )

        with st.form("elemzes"):
            hazai = st.selectbox("Hazai csapat", csapatok)
            vendeg = st.selectbox(
                "Vendégcsapat", csapatok, index=1
            )

            st.caption(
                "Az aktuális fogadóirodai oddsokat add meg."
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

                    st.write(
                        f"Becsült gólátlag: **{gh:.2f} – {gv:.2f}**"
                    )
                    st.caption(
                        f"{nh} hazai és {nv} idegenbeli meccs alapján."
                    )

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

                except ValueError as hiba:
                    st.error(str(hiba))

    with teszt:
        st.subheader("Időrendi visszateszt")

        st.write(
            "Minden meccsnél kizárólag a korábbi napok "
            "eredményeiből számolunk. Az aznapi meccsek "
            "nem kerülnek a tanítóadatokba."
        )

        st.caption(
            "Kezdeti feltétel: 60 ligameccs, továbbá "
            "legalább 3 megfelelő hazai és "
            "3 idegenbeli csapatmeccs."
        )

        if st.button(
            "Visszateszt indítása",
            use_container_width=True,
        ):
            with st.spinner(
                "Korábbi mérkőzések tesztelése…"
            ):
                sorok, kihagyott = visszateszt(meccsek)

            st.metric("Tesztelt mérkőzések", len(sorok))
            st.caption(
                f"Kihagyott mérkőzések: {kihagyott}"
            )

            if not sorok:
                st.warning(
                    "Még nincs elég adat. "
                    "Válaszd a 2025/26-os idényt."
                )

            else:
                modell = sum(r[1] for r in sorok) / len(sorok)
                alap = sum(r[2] for r in sorok) / len(sorok)

                st.metric(
                    "Modell Brier-pontszáma",
                    f"{modell:.3f}",
                )
                st.metric(
                    "Ligaátlagos becslés Brier-pontszáma",
                    f"{alap:.3f}",
                )

                st.caption(
                    "Kisebb érték = pontosabb valószínűségi "
                    "becslés. Az itt használt háromkimeneteles "
                    "Brier-pontszám 0 és 2 közötti."
                )

                if modell < alap:
                    st.success(
                        "A modell ezen a mintán jobb volt "
                        "a ligaátlagos becslésnél."
                    )
                else:
                    st.warning(
                        "A modell ezen a mintán nem volt jobb "
                        "a ligaátlagos becslésnél."
                    )

                st.write(
                    "A referencia a korábbi napok hazai "
                    "győzelmeinek, döntetlenjeinek és "
                    "vendéggyőzelmeinek arányát használja, "
                    "kimenetelenként egy kezdeti mintával. "
                    "Mindkét módszert ugyanazokon a "
                    "mérkőzéseken értékeljük."
                )

                st.warning(
                    "Ez pontosságvizsgálat. Fogadási nyereséget "
                    "nem mér, és nem bizonyít jövőbeli "
                    "eredményességet."
                )

    with st.expander("Módszer és korlátok"):
        st.write(
            "Ligaátlaghoz viszonyított hazai és idegenbeli "
            "gólátlagok, öt ligaátlagos mintameccses "
            "simítással és független Poisson-eloszlással. "
            "Sérüléseket és átigazolásokat nem kezelünk; "
            "kevés meccsnél nagyobb a bizonytalanság."
        )

        st.write(
            "A mérkőzéselemzés teljes idényadatot használ, "
            "ezért korábbi meccsen nem előzetes teszt. "
            "A Visszateszt fül ezt időrendben kezeli. "
            "A várható hozam: "
            "(becsült esély × odds − 1) × 100%. "
            "Nem garantált nyereség."
        )

    st.caption(
        "Adatforrás: Football-Data.co.uk • "
        "Legfeljebb 24 órás gyorsítótár."
    )


if __name__ == "__main__":
    main()
