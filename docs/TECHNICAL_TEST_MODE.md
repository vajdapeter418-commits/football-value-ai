# Biztonságos technikai tesztmód – terv, használat és ellenőrzési jelentés

## Hatókör és forrásellenőrzés

A fejlesztés alapja: `vajdapeter418-commits/football-value-ai`,
`feature/12-market-detective`, `10683e507bb07c1cc35ca319f5cddce89945ef15`.
Külön fejlesztési ág: `feature/safe-technical-test-mode`.
A PR célága kizárólag `feature/12-market-detective`; nem `main`.

A README és a kód alapján a belépési pont `streamlit_app.py`, és ezen az ágon
szerepel a Piaci nyomozó. A verziózott fájllistában nincs Streamlit telepítési
konfiguráció vagy olyan manifest, amely a
`https://football-value-ai-market-test.streamlit.app/` címet ehhez az ághoz kötné.
A `.github/workflows/tests.yml` tesztelést végez, nem telepít.
A Streamlit kezelőfelületéhez nincs adminisztrátori kapcsolat; a publikus oldal
elérése a helyi hálózaton és a webes olvasóval sem sikerült. Ezért a tényleges
repository/branch/entrypoint összerendelés **nem igazolt**; a felhasználó által
megadott hozzárendelés alapján készült az alapértelmezetten kikapcsolt fejlesztés.
Nincs hozzáférés vagy módosítás az éles Streamlit-konfigurációhoz.

Az eredeti piacarchívum `MarketArchive` osztálya a meglévő privát GitHub-kapcsolatot
használja (`market-research` ág, `archive/market-research.json`). Ezt a technikai
tesztmód nem használja. A napló, az odds-SQLite, a korábbi archívumok és a hozzájuk
tartozó konfigurációk érintetlenek.

## A megvalósítás előtt rögzített terv

1. Külön ág létrehozása a megadott, rögzített forráscommitból.
2. Alapértelmezetten tiltott, külön bekapcsoláshoz és pontos tesztcímhez kötött felület.
3. Saját TESZT tároló, fix fájlnévvel és formátummal, az alkalmazás könyvtárán kívül.
4. Strukturált kézi 1X2 próbaadatok és eredmények mentése/visszaolvasása.
5. Új folyamatból visszaolvasás, elkülönítés, konkurens írás és időrendi visszateszt ellenőrzése.
6. Külön PR, részletes jelentés; automatikus merge vagy deploy nélkül.

## Működés és elkülönítés

A `FVA_TECH_TEST_ENABLED=1` bekapcsolás esetén a belépési pont kizárólag a technikai
felületet futtatja, majd megáll. Nem jelenik meg az eredeti alkalmazás navigációja,
és nem indítja el az eredeti adatbetöltést vagy az archívum felületét.
Hiányzó bekapcsolás esetén az eredeti alkalmazás működése változatlan.
Külön technikai felület közvetlen meghívásakor is kötelező a bekapcsolás.

Mentéshez a `st.context.url` által visszaadott HTTPS URL authority részének pontosan
`football-value-ai-market-test.streamlit.app` értékűnek kell lennie. Másik cím,
HTTP, felhasználónévvel ellátott URL, alternatív port vagy hiányzó URL tiltást jelent.
Ez alkalmazásszintű védőkorlát, nem felhasználó-hitelesítés és nem a telepítés
azonosságának független bizonyítéka. A platform tényleges hozzárendelését és a
tesztalkalmazás hozzáférését az üzemeltetőnek kell ellenőriznie aktiválás előtt.
Ha a telepített Streamlit-verzió nem szolgáltat `st.context.url` értéket, a mód
zárva marad; nincs Host fejlécből vagy query paraméterből képzett kerülőút.

A `FVA_TECH_TEST_ROOT` kizárólag abszolút, saját, új könyvtárra mutathat,
amelynek utolsó eleme `football-value-ai-market-test`. A szülőkönyvtárnak már
léteznie kell. Az alkalmazás forráskönyvtárán belüli útvonal tiltott.
A program létrehozza a saját `TESZT-ONLY` markerét és `TESZT.sqlite3` fájlját.
Már létező, marker nélküli könyvtárat nem vesz birtokba. A saját adatbázist
újranyitáskor csak olvassa a formátumellenőrzéshez, nem futtat rajta migrációt.

Tiltott: idegen fájl/tábla, eltérő adatbázis-formátum, symlink, hardlink,
symlinkes szülőút, más által írható TESZT könyvtár, a tároló utólagos lecserélése.
A fájlokat minden művelet előtt ellenőrzi, és a kapcsolatokat lezárja.
A fájlrendszert a folyamat felhasználója kezeli; ez nem védelmi határ privilegizált
vagy ugyanazon felhasználóként futó rosszindulatú folyamat ellen. A dedikált kötet
és a telepítési jogosultságok üzemeltetői felelősségűek.

A technikai tároló figyelmen kívül hagyja az eredeti DB-útvonalakat és GitHub-
archívumbeállításokat. Hiányzó/hibás TESZT tároló esetén hibaüzenet jelenik meg:
**nincs fallback sem éles adatbázisra, sem korábbi naplóra**.
Nincs adatimport, éles exportformátum vagy átvezetés a régi archívumokba.

A kézi adatok automatikus `TESZT-` mérkőzésazonosítót és `TESZT ` csapatneveket
kapnak. A fogadóiroda és a forrás fixen TESZT; a forráscím a nem használható
`https://example.invalid/TESZT`, amelyet a program soha nem kér le.
A `manual_verified` technikai jelző itt kizárólag a szintetikus visszajátszási
adapter része; nem hitelesített valódi eseményt jelent. Tickets/handle és hírek
nincsenek kitalálva: hiányzó adatként szerepelnek.

A megfigyelés, a kezdés és az eredmény befejezése időzónás UTC-kompatibilis időpont.
A rögzítési idő kizárólag a szerver órája: nem adható meg és nem dátumozható vissza.
Érvénytelen ár, NaN, jövőbeli megfigyelés és idő előtt bevitt eredmény nem menthető.
A módosítás tranzakciós; a hash-láncot minden visszaolvasás ellenőrzi.

## Tartósság: igazolt és nem igazolt

**Igazolt:** SQLite commit után, ugyanazon megmaradó fájlrendszeren egy teljesen új
Python-folyamat ugyanazokat a mentett adatokat olvassa vissza. Az adat nem
`session_state`-ben vagy kizárólag memóriában él. Két konkurens mentés is megmarad.

**Nem igazolt:** a tényleges Streamlit Community Cloud konténer/kötet megmaradása
reboot, hibernálás, újratelepítés vagy konténercsere után. A helyi SQLite erre
önmagában nem garancia. A módhoz jelenleg nincs új, független külső tartós
felhőtároló integrálva. Ennek hiányában ne tekintsük felhőben tartósnak a módot,
és ne adjunk meg helyette éles adatbázist vagy a meglévő privát archívumot.

Az aktuális munka nem aktiválta a módot és nem változtatott semmilyen deploymenten.
Jóváhagyott későbbi aktiválás előtt ellenőrizni kell a platform repository/ág/fájl
beállítását, az alkalmazás hozzáférését, a Streamlit URL API elérhetőségét és a külön
tartós kötetet. A nem titkos konfigurációs nevek fent szerepelnek; API-kulcsot,
tokent és jelszót a mód nem kér, nem olvas és nem ír.

Későbbi kézi felhős tartósságellenőrzés: egy egyedi TESZT azonosító és odds mentése,
a megjelenő szerver-rögzítési idő feljegyzése, kizárólag a tesztalkalmazás
újraindítása, majd új böngészőmunkamenetben ugyanazon azonosító/odds/idő ellenőrzése.
Az eredményt a platform futó commitjával és a tároló típusával kell dokumentálni.
Ez a lépés most **nem történt meg**; az alkalmazás nem lett újraindítva.

## Automatizált tesztek és eredmények

Helyi környezet: Python 3.12, valódi Streamlit nincs telepítve. A függőség telepítését
a hálózati/proxy elérés akadályozta. A meglévő CI telepíti a `requirements.txt`
függőségeit, és az összes tesztet futtatja, beleértve az új runtime-teszteket.

Fókuszált parancs:

```sh
PYTHONPATH=tests:. python -m unittest test_technical_test test_technical_test_runtime test_backtest test_market_research test_market_final_review -v
python -m compileall -q .
git diff --check
```

Helyi eredmény: **55 tesztből 49 sikeres, 6 Streamlit runtime-teszt kihagyva**.
A fordíthatósági és whitespace-ellenőrzés sikeres.

| Ellenőrzés | Helyi eredmény |
| --- | --- |
| Kézi TESZT mérkőzés és teljes 1X2 odds mentése/visszaolvasása | Sikeres |
| Új Python-folyamatból visszaolvasás azonos adatállapottal | Sikeres |
| Host, külön engedély, forráskönyvtáron kívüli dedikált útvonal | Sikeres |
| Idegen DB, extra tábla, symlink/hardlink, utólagos fájlcsere elutasítása | Sikeres |
| Korábbi napló/éles DB helyett ideiglenes sentinel fájlok változatlansága | Sikeres |
| Eredeti DB-konfiguráció és szintetikus credential-sentinel figyelmen kívül hagyása | Sikeres |
| Két konkurens mentés megőrzése | Sikeres |
| Hibás adatok tranzakciós elutasítása, hash-integritás | Sikeres |
| Valódi `market_backtest.backtest` ismert tesztárakkal és eredménnyel | Sikeres |
| Régi forrásidővel, de későn rögzített odds kizárása; korábbi sor invarianciája | Sikeres |
| Döntési határ pontosan engedett; +1 mikrosec rögzítés kizárt | Sikeres |
| Eredmény hiányában nincs kiértékelt mérkőzés; címke nem módosítja a megfigyelést | Sikeres |
| Meglévő regresszió: későbbi odds/hír, módosult kezdés, fejl./teszt címkehatár | Sikeres |
| Meglévő Poisson regresszió: aznapi/későbbi eredmény nem jut a tanulómintába | Sikeres |
| Valódi Streamlit űrlapmentés, új UI-session, tiltási utak, hibakitakarás, visszateszt | Helyben kihagyva; GitHub CI-ben mind a 6 sikeres |
| Futó URL tényleges deployment-hozzárendelése | Nem igazolt |
| Tényleges felhős reboot utáni tartósság | Nem igazolt |

A teljes helyi regresszió a hiányzó `streamlit` import miatt nem igazolható ebben
a környezetben; a fókuszált helyi csomag ezt nem helyettesíti.

**GitHub Actions: 134/134 teszt sikeres, kihagyás és hiba nélkül**, valódi
Streamlit-függőséggel. Mind a 11 új tárolási/biztonsági és mind a 6 új runtime-
ellenőrzés lefutott. A `compileall` és a `git diff --check HEAD^ HEAD` is sikeres.
Ellenőrzött kódcommit: `28f113e3c9aa338de09bf50632fb3e8cb71abff9`.
[Ellenőrzési futás és napló](https://github.com/vajdapeter418-commits/football-value-ai/actions/runs/40220821824).
Az AppTest a böngésző URL-értékét helyettesíti: ez tényleges Streamlit runtime-
ellenőrzés, de nem a publikus alkalmazás vagy a platform-hozzárendelés igazolása.
A 13 meglévő felső szintű függvény AST összehasonlítással változatlan.

## Nyitott pontok és további teendők

1. Az alkalmazás–tároló–ág összerendelés igazolása a Streamlit kezelőfelületén.
2. Kizárólag tesztadatokhoz dedikált tartós kötet vagy külön külső tároló biztosítása.
   Enélkül a felhős tartósság követelménye nyitott marad; nincs éles tárolós helyettesítés.
3. A PR későbbi módosításai után az új fejcommit teljes GitHub Actions futásának
   ellenőrzése. A fenti kódcommit teljes regressziója sikeres.
4. Külön jóváhagyott teszttelepítés után kézi böngészős és reboot-ellenőrzés.
5. Az egyetlen kézi odds-pillanatkép a baseline technikai értékelésére elegendő;
   mozgásszabályhoz ugyanahhoz a TESZT fixture-höz több, külön időpontú mentés kell.
   A csak szintetikus adatokon elért eredmény nem üzleti vagy fogadási előny igazolása.

A változtatás nem érinti az eredeti modell- vagy visszatesztfüggvényeket,
archívumimplementációkat, éles fájlokat, meglévő naplókat vagy hitelesítő adatokat.
