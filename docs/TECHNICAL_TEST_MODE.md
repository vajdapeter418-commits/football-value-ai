# Elkülönített technikai TESZT mód

A PR #14 aktuális biztonsági vizsgálata, a bizonyított hibák és javítások,
a külön tartós adattárolás terve és a nyitott korlátok:
[PR14_SECURITY_REVIEW.md](PR14_SECURITY_REVIEW.md).

## Aktuális működés

A tesztalkalmazás külön belépési pontja `technical_test_app.py`.
A `streamlit_app.py` nem importál technikai tesztmodult, és környezeti kapcsoló
nem válthatja át technikai módba. Az eredeti alkalmazás felülete megmarad.

Az új felület csak együttesen teljesülő feltételekkel nyit tárolót:

- `FVA_TECH_TEST_ENABLED=1`;
- a Streamlit context URL authority pontosan
  `football-value-ai-market-test.streamlit.app`, HTTPS protokollal;
- Streamlit OIDC bejelentkezés, ellenőrzött email claim és külön
  `FVA_TECH_TEST_ALLOWED_EMAILS` engedélylista;
- `FVA_TECH_TEST_ROOT`: saját, abszolút, forráskönyvtáron kívüli
  `football-value-ai-market-test` könyvtár létező szülővel.

Hiányzó feltétel tiltást jelent. A bejelentkezési gomb az `st.login()` API-t
használja; ehhez a tesztdeployment saját OIDC konfigurációját később külön be
kell állítani. Ebben a munkában sem hitelesítő adat, sem platformbeállítás nem
módosult. A host nem helyettesíti a látogatói hitelesítést vagy a deployment
azonosságának üzemeltetői ellenőrzését.

A tároló csak mesterséges TESZT adatot kezel, fix SQLite fájlnévvel és markerrel.
A rögzítési időt a szerver állítja; nincs visszadátumozás, adatimport vagy éles
DB/archívum fallback. Az eredeti napló és a privát GitHub-archívum érintetlen.
A fájlműveletek rögzített könyvtári fájlleírókon, linkkövetés nélkül történnek.
A SQLite kizárólag memóriában dolgozik, a lemezre mentést folyamatok közötti
zár és atomi csere védi. Azonos OS-felhasználójú támadó kizárása nem garantált.

A helyi SQLite megmaradó fájlrendszeren új Python-folyamatból visszaolvasható.
Streamlit Community Cloud redeploy utáni tartósságra nem ad garanciát.
A külön menedzselt PostgreSQL-tároló részletes terve a kapcsolt jelentésben van;
ez még nem megvalósított vagy aktivált külső integráció.

## Ellenőrzés

```sh
python -m unittest discover -s tests -v
python -m compileall -q .
git diff --check
```

A teljes, valódi Streamlit-függőséggel futó csomag a meglévő GitHub Actions
workflow feladata. Az AppTest helyettesített URL/identitása nem bizonyítja a
futó felhős app hozzárendelését, az OIDC integrációját vagy a redeploy-tartósságot.
A jelen munka nem aktiválja a tesztmódot, nem telepít és nem indít újra appot.
