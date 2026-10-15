import csv
import io
import math
from urllib.request import Request, urlopen

import streamlit as st

st.set_page_config(
    page_title="Football Value AI",
    page_icon="⚽",
    layout="centered",
)


@st.cache_data(ttl=86400)
def adatok_betoltese():
    url = "https://www.football-data.co.uk/mmz4281/2526/E0.csv"
    keres = Request(url, headers={"User-Agent": "FootballValueAI/1.0"})
    with urlopen(keres, timeout=30) as valasz:
        szoveg = valasz.read().decode("utf-8-sig")

    olvaso = csv.DictReader(io.StringIO(szoveg))
    kotelezo = {"Div", "HomeTeam", "AwayTeam", "FTHG", "FTAG"}
    if not kotelezo.issubset(olvaso.fieldnames or []):
        raise ValueError("Az adatforrás formátuma megváltozott.")

    meccsek = []
    for sor in olvaso:
        if sor["Div"] != "E0":
            continue
        if not sor["FTHG"] or not sor["FTAG"]:
            continue
        h, v = int(sor["FTHG"]), int(sor["FTAG"])
        if h < 0 or v < 0:
            raise ValueError("Érvénytelen gólszám.")
        meccsek.append(
            (sor["HomeTeam"], sor["AwayTeam"], h, v)
        )

    if len(meccsek) < 20:
        raise ValueError("Nincs elegendő mérkőzés.")
    return meccsek


def becsles(meccsek, hazai, vendeg):
    liga_h = sum(m[2] for m in meccsek) / len(meccsek)
    liga_v = sum(m[3] for m in meccsek) / len(meccsek)
    h = [m for m in meccsek if m[0] == hazai]
    v = [m for m in meccsek if m[1] == vendeg]

    if not h or not v or min(liga_h, liga_v) <= 0:
        raise ValueError("Nincs elegendő megfelelő csapatadat.")

    prior = 5
    h_lott = (sum(m[2] for m in h) + prior * liga_h) / (len(h) + prior)
    h_kapott = (sum(m[3] for m in h) + prior * liga_v) / (len(h) + prior)
    v_lott = (sum(m[3] for m in v) + prior * liga_v) / (len(v) + prior)
    v_kapott = (sum(m[2] for m in v) + prior * liga_h) / (len(v) + prior)

    gol_h = h_lott * v_kapott / liga_h
    gol_v = v_lott * h_kapott / liga_v

    if not all(math.isfinite(x) and 0 < x <= 20 for x in [gol_h, gol_v]):
        raise ValueError("A gólátlag kívül esik a modell tartományán.")

    ph, pv = [math.exp(-gol_h)], [math.exp(-gol_v)]
    for k in range(1, 101):
        ph.append(ph[-1] * gol_h / k)
        pv.append(pv[-1] * gol_v / k)

    eselyek = [0.0, 0.0, 0.0]
    for i, p in enumerate(ph):
        for j, q in enumerate(pv):
            index = 0 if i > j else 1 if i == j else 2
            eselyek[index] += p * q

    osszeg = sum(eselyek)
    return [p / osszeg for p in eselyek], gol_h, gol_v


st.title("⚽ Football Value AI")
st.caption("Premier League • Statisztikai esélybecslés")

st.info(
    "A 2025/26-os idény eredményeiből számolunk. "
    "Ez nem élő adat és nem AI-előrejelzés."
)

try:
    with st.spinner("Premier League-adatok betöltése…"):
        meccsek = adatok_betoltese()
except Exception:
    st.error(
        "Most nem sikerült elérni vagy feldolgozni az adatforrást. "
        "Próbáld meg később újratölteni az oldalt."
    )
    st.stop()

csapatok = sorted(
    {m[0] for m in meccsek} | {m[1] for m in meccsek}
)
st.caption(f"{len(meccsek)} mérkőzés • {len(csapatok)} csapat")

st.warning(
    "A modell az új idény formáját, sérüléseit és átigazolásait "
    "nem kezeli. Csak a 2025/26-os csapatok választhatók."
)

with st.form("elemzes"):
    hazai = st.selectbox("Hazai csapat", csapatok)
    vendeg = st.selectbox("Vendégcsapat", csapatok, index=1)

    st.subheader("Aktuális oddsok")
    st.caption("Írd át ezeket a fogadóirodánál látott oddsokra.")

    odds_h = st.number_input(
        "Hazai győzelem oddsa",
        min_value=1.01, value=2.30, step=0.01, format="%.2f",
    )
    odds_d = st.number_input(
        "Döntetlen oddsa",
        min_value=1.01, value=3.20, step=0.01, format="%.2f",
    )
    odds_v = st.number_input(
        "Vendéggyőzelem oddsa",
        min_value=1.01, value=3.00, step=0.01, format="%.2f",
    )

    inditas = st.form_submit_button(
        "Elemzés indítása", use_container_width=True
    )

if inditas:
    if hazai == vendeg:
        st.error("Válassz két különböző csapatot.")
    else:
        try:
            eselyek, gol_h, gol_v = becsles(meccsek, hazai, vendeg)
        except ValueError as hiba:
            st.error(str(hiba))
            st.stop()

        st.subheader(f"{hazai} – {vendeg}")
        st.write(f"Becsült gólátlag: **{gol_h:.2f} – {gol_v:.2f}**")

        nevek = ["Hazai győzelem", "Döntetlen", "Vendéggyőzelem"]
        for nev, esely, odds in zip(
            nevek, eselyek, [odds_h, odds_d, odds_v]
        ):
            hozam = (esely * odds - 1) * 100
            with st.container(border=True):
                st.subheader(nev)
                st.metric("Becsült esély", f"{esely * 100:.1f}%")
                st.write(f"Fair odds: **{1 / esely:.2f}**")
                st.write(f"Megadott odds: **{odds:.2f}**")
                st.metric("Becsült várható hozam", f"{hozam:+.1f}%")
                if hozam > 0:
                    st.success("Modell szerint pozitív várható érték.")
                else:
                    st.info("Modell szerint nincs pozitív várható érték.")

with st.expander("Hogyan számol?"):
    st.write(
        "A hazai és idegenbeli lőtt, illetve kapott gólátlagokat "
        "a liga átlagaihoz viszonyítjuk. Öt ligaátlagos "
        "mintamérkőzéssel mérsékeljük a szélsőségeket, majd "
        "független Poisson-eloszlással számoljuk az esélyeket."
    )
    st.write(
        "Várható hozam = (becsült valószínűség × odds − 1) × 100%. "
        "A modell nincs visszamérve, nyereségessége nem igazolt. "
        "A teljes idény adatait használja, ezért az idény korábbi "
        "meccseinek elemzése nem előzetes teszt."
    )

st.caption("Adatforrás: Football-Data.co.uk • Nem garantált nyereség.")
