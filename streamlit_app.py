import streamlit as st

st.set_page_config(
    page_title="Football Value AI",
    page_icon="⚽",
    layout="centered",
)

st.title("⚽ Football Value AI")
st.caption("Futballelemzés magyarul • Első változat")

st.info(
    "Ez a változat a saját esélybecslésedből számol. "
    "Nem használ élő adatot vagy AI-előrejelzést."
)

with st.form("elemzes"):
    st.subheader("Mérkőzés")
    hazai = st.text_input("Hazai csapat", placeholder="Például: Ferencváros")
    vendeg = st.text_input("Vendégcsapat", placeholder="Például: Újpest")

    st.subheader("Saját esélybecslés")
    st.caption("A három esély összege legyen 100%.")

    hazai_esely = st.number_input(
        "Hazai győzelem esélye (%)",
        min_value=0.0, max_value=100.0, value=45.0, step=1.0,
    )
    dontetlen_esely = st.number_input(
        "Döntetlen esélye (%)",
        min_value=0.0, max_value=100.0, value=30.0, step=1.0,
    )
    vendeg_esely = st.number_input(
        "Vendéggyőzelem esélye (%)",
        min_value=0.0, max_value=100.0, value=25.0, step=1.0,
    )

    st.subheader("Fogadóirodai oddsok")
    hazai_odds = st.number_input(
        "Hazai győzelem oddsa",
        min_value=1.01, value=2.30, step=0.01, format="%.2f",
    )
    dontetlen_odds = st.number_input(
        "Döntetlen oddsa",
        min_value=1.01, value=3.20, step=0.01, format="%.2f",
    )
    vendeg_odds = st.number_input(
        "Vendéggyőzelem oddsa",
        min_value=1.01, value=3.00, step=0.01, format="%.2f",
    )

    inditas = st.form_submit_button(
        "Elemzés indítása", use_container_width=True
    )

if inditas:
    osszeg = hazai_esely + dontetlen_esely + vendeg_esely

    if not hazai.strip() or not vendeg.strip():
        st.error("Add meg mindkét csapat nevét.")
    elif hazai.strip().casefold() == vendeg.strip().casefold():
        st.error("Két különböző csapatot adj meg.")
    elif abs(osszeg - 100.0) > 0.01:
        st.error(f"Az esélyek összege {osszeg:.1f}%. Legyen pontosan 100%.")
    else:
        st.subheader(f"{hazai.strip()} – {vendeg.strip()}")

        eredmenyek = [
            ("Hazai győzelem", hazai_esely, hazai_odds),
            ("Döntetlen", dontetlen_esely, dontetlen_odds),
            ("Vendéggyőzelem", vendeg_esely, vendeg_odds),
        ]

        for nev, esely, odds in eredmenyek:
            valoszinuseg = esely / 100
            varhato_hozam = (valoszinuseg * odds - 1) * 100
            nullszaldos_esely = 100 / odds
            fair_odds = (
                f"{1 / valoszinuseg:.2f}"
                if valoszinuseg > 0
                else "Nem számítható 0% esélynél"
            )

            with st.container(border=True):
                st.markdown(f"### {nev}")
                st.metric(
                    "Becsült várható hozam",
                    f"{varhato_hozam:+.1f}%",
                )
                st.write(f"Saját becslés: **{esely:.1f}%**")
                st.write(f"Megadott odds: **{odds:.2f}**")
                st.write(f"Nullszaldóhoz szükséges esély: **{nullszaldos_esely:.1f}%**")
                st.write(f"Saját becslés szerinti fair odds: **{fair_odds}**")

                if varhato_hozam > 0:
                    st.success("A megadott becslés szerint pozitív várható érték.")
                else:
                    st.warning("A megadott becslés szerint nincs pozitív várható érték.")

        with st.expander("Mit jelentenek az eredmények?"):
            st.write(
                "Várható hozam = (becsült valószínűség × odds − 1) × 100. "
                "Ez sok hasonló fogadás elméleti átlaga, ha az esélybecslés pontos; "
                "nem az adott mérkőzés garantált eredménye."
            )
            st.write(
                "A fair odds a saját becsült valószínűséged reciproka. "
                "A nullszaldóhoz szükséges esély a megadott odds reciproka."
            )

st.divider()
st.caption(
    "Tájékoztató számítás, nem garantált nyereség. "
    "A becslés pontatlansága az eredményt is befolyásolja."
)
