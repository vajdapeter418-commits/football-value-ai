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
        raise ValueError(
            "Nincs elég megfelelő hazai vagy idegenbeli adat."
        )

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
        raise ValueError(
            "A gólátlag kívül esik a modell tartományán."
        )

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


def main():
    st.set_page_config(
        page_title="Football Value AI",
        page_icon="⚽",
        layout="centered",
    )

    st.title("⚽ Football Value AI")
    st.caption(
        "Premier League • Magyar nyelvű statisztikai elemzés"
    )

    ideny = st.selectbox(
        "Elemzett idény",
        ["2026/27", "2025/26"],
    )

    kod = {
        "2026/27": "2627",
        "2025/26": "2526",
    }[ideny]

    st.info(
        f"A(z) {ideny}-es idény eredményeiből számolunk. "
        "Ez nem élő adat és nem AI-előrejelzés."
    )

    @st.cache_data(ttl=86400)
    def letoltes(idenykod):
        url = (
            "https://www.football-data.co.uk/mmz4281/"
            f"{idenykod}/E0.csv"
        )

        keres = Request(
            url,
            headers={"User-Agent": "FootballValueAI/1.0"},
        )

        with urlopen(keres, timeout=30) as valasz:
            return feldolgozas(valasz.read())

    try:
        with st.spinner("Mérkőzések betöltése…"):
            meccsek = letoltes(kod)

    except Exception as hiba:
        st.error(
            "Nem sikerült betölteni az idény adatait. "
            "Válaszd a másik idényt, vagy próbáld később."
        )

        with st.expander("Hiba részletei"):
            st.text(f"{type(hiba).__name__}: {hiba}")

        st.stop()

    csapatok = sorted(
        {m[0] for m in meccsek}
        | {m[1] for m in meccsek}
    )

    if len(csapatok) < 2:
        st.error("Nincs elegendő csapatadat.")
        st.stop()

    elso = min(m[4] for m in meccsek)
    utolso = max(m[4] for m in meccsek)

    st.caption(
        f"{len(meccsek)} mérkőzés • "
        f"{len(csapatok)} csapat • "
        f"{elso:%Y.%m.%d.}–{utolso:%Y.%m.%d.}"
    )

    st.warning(
        "Kevés meccsnél bizonytalanabb a becslés. "
        "A modell nem kezeli a sérüléseket, átigazolásokat "
        "és kezdőcsapatokat. "
        "Minden betöltött meccs azonos súlyú."
    )

    with st.form("elemzes"):
        hazai = st.selectbox("Hazai csapat", csapatok)
        vendeg = st.selectbox(
            "Vendégcsapat",
            csapatok,
            index=1,
        )

        st.subheader("Aktuális oddsok")
        st.caption(
            "Írd be a fogadóirodánál látott oddsokat."
        )

        oh = st.number_input(
            "Hazai győzelem oddsa",
            min_value=1.01,
            value=2.30,
            step=0.01,
            format="%.2f",
        )

        od = st.number_input(
            "Döntetlen oddsa",
            min_value=1.01,
            value=3.20,
            step=0.01,
            format="%.2f",
        )

        ov = st.number_input(
            "Vendéggyőzelem oddsa",
            min_value=1.01,
            value=3.00,
            step=0.01,
            format="%.2f",
        )

        inditas = st.form_submit_button(
            "Elemzés indítása",
            use_container_width=True,
        )

    if inditas:
        if hazai == vendeg:
            st.error("Válassz két különböző csapatot.")

        else:
            try:
                eselyek, gh, gv, nh, nv = becsles(
                    meccsek,
                    hazai,
                    vendeg,
                )

            except ValueError as hiba:
                st.error(str(hiba))
                st.stop()

            st.subheader(f"{hazai} – {vendeg}")

            st.write(
                f"Becsült gólátlag: **{gh:.2f} – {gv:.2f}**"
            )

            st.caption(
                f"Csapatadat: {nh} hazai és "
                f"{nv} idegenbeli mérkőzés."
            )

            nevek = [
                "Hazai győzelem",
                "Döntetlen",
                "Vendéggyőzelem",
            ]

            for nev, p, odds in zip(
                nevek,
                eselyek,
                [oh, od, ov],
            ):
                hozam = (p * odds - 1) * 100

                with st.container(border=True):
                    st.subheader(nev)

                    st.metric(
                        "Becsült esély",
                        f"{p * 100:.1f}%",
                    )

                    st.write(
                        f"Fair odds: **{1 / p:.2f}** • "
                        f"Megadott odds: **{odds:.2f}**"
                    )

                    st.metric(
                        "Modell szerinti várható hozam",
                        f"{hozam:+.1f}%",
                    )

                    if hozam > 0:
                        st.success(
                            "A modell szerint pozitív "
                            "várható érték."
                        )
                    else:
                        st.info(
                            "A modell szerint nincs pozitív "
                            "várható érték."
                        )

    with st.expander("Hogyan számol?"):
        st.write(
            "Hazai és idegenbeli gólátlagokat viszonyítunk "
            "a liga átlagaihoz. Öt ligaátlagos "
            "mintamérkőzéssel mérsékeljük a kis minták "
            "szélsőségeit, majd független "
            "Poisson-eloszlással számolunk."
        )

        st.write(
            "Várható hozam = "
            "(becsült valószínűség × odds − 1) × 100%. "
            "Ez nem garantált eredmény. A modell pontossága "
            "és nyereségessége nincs visszamérve."
        )

        st.write(
            "A teljes kiválasztott idény elérhető "
            "eredményeit használjuk. Az idény korábbi "
            "meccseinek elemzése ezért nem előzetes teszt. "
            "A kerekített esélyek összege kis mértékben "
            "eltérhet 100%-tól."
        )

    st.caption(
        "Adatforrás: Football-Data.co.uk • "
        "Az adatokat legfeljebb 24 órára gyorsítótárazzuk."
    )


if __name__ == "__main__":
    main()
