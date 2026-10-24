# Football Value AI

A meglévő Premier League Poisson-modell, Brier-visszateszt és FPL-panel mellett külön oldalsávos **Oddsmozgás-nyomozó** modul.

## Telepítés a meglévő Streamlit-alkalmazásba

1. A csomag összes fájlját töltsd fel a kódtár gyökerébe, a módosított `streamlit_app.py` fájllal együtt. A Streamlit belépési pont továbbra is `streamlit_app.py`.
2. A `requirements.txt` változatlan: `streamlit>=1.40,<2`. A grafikonok a Streamlit pandas-függőségét használják.
3. Helyben: `pip install -r requirements.txt`, majd `streamlit run streamlit_app.py`.
4. Az oldalsávon válaszd az Oddsmozgás-nyomozót. A korábbi elemzés és FPL ugyanazon az eredeti oldalon marad.

## Adatkapcsolatok

A Streamlit alkalmazás **Settings → Secrets** felületén (vagy szerveroldali környezeti változóként):

```toml
ODDS_API_KEY = "sajat-kulcs"
BETFAIR_APP_KEY = "sajat-app-kulcs"
BETFAIR_SESSION_TOKEN = "ervenyes-session-token"
```

Ezeket ne töltsd fel GitHubra. A Betfair munkamenet lejárhat, megújítását a modul nem automatizálja. Nem fogad, nem indít pénzmozgást, csak olvasási műveleteket hív.

- [The Odds API v4](https://the-odds-api.com/liveapi/guides/v4/): `soccer_…` sportkulcs, konkrét eseményazonosító és az API-ban szereplő pontos csapatnevek szükségesek. EU-régió, decimális, teljes háromkimeneteles h2h piac. A kulcsot a szolgáltatónál kell igényelni; ingyenes kvóta és lefedettség szolgáltatófüggő. A történelmi adatot nem kéri le, minden frissítés új megfigyelést tárol. A `last_update` a szolgáltató megfigyelési ideje, nem bizonyítottan az iroda tényleges oddsállítási ideje. Az eseményazonosítót a szolgáltató eseménylistájában lehet ellenőrizni.
- [Betfair listMarketBook](https://betfair-developer-docs.atlassian.net/wiki/spaces/1smk3cen4v3lu3yomq5qye0ni/pages/2687510/listMarketBook): hivatalos API-hozzáférés szükséges; ennek díjmentességét nem ígérjük. Labdarúgó MATCH_ODDS piacot és dátumot ellenőriz. A marketId-t és a hazai/döntetlen/vendég selectionId-ket a felhasználónak a Betfairen ellenőriznie kell. Piaci `totalMatched` és `runners.totalMatched` külön kerül mentésre, hiány esetén null, soha nem helyettesítjük a másikból kiszámított adattal. A pénznemet a számla alapján kell kiválasztani. A késleltetési jelzőt megőrzi. A megfigyelési idő a lekérés ideje, nem a kötés ideje. A kumulatív forgalom nem nettó pénzáramlás, és nem mondja meg, ki milyen összeget tett fel.
- Google News RSS: kattintásra keres a két csapatra a mérkőzés körüli napokban. A találatok **nem ellenőrzött** hírek, cím/link/közzétételi idő/kiadó megőrzésével. A tartalmat a forrásnál kell ellenőrizni. Elsődleges klub-, liga- vagy UEFA-közlések kézzel is rögzíthetők. Nincs állítás automatikusan megállapított okról.
- Nincs bookmaker-weboldalakat megkerülő scraping. A szolgáltatás előfizetésének és az adatok megjelenítésének jogát a szolgáltatói feltételekkel egyeztetni kell.

## Első vizsgálat

FC Iberia 1999–Mjällby AIF, 2026-10-22, vizsgálatazonosító: `iberia-mjallby-2026-10-22`. A mérkőzés rekordja a felhasználó kéréséből származik, ezért user_reported. Sem odds, sem forgalom, sem hír, sem eredmény nincs beültetve. A UEFA kluboldalán megjelenő párosítás önmagában nem igazolja a konfigurált API-azonosítókat: https://www.uefa.com/uefaconferenceleague/clubs/2605905/matches/

## Adatvédelem és ellenőrzési státusz

- Minden bizonyítékhoz forrás, forrásidő (ha ismert), tényleges rögzítési idő, státusz és eredeti adattartalom tartozik. Az adatbázis időpontjai UTC-ben vannak.
- `source_checked`: a program a konfigurált API-ból beolvasta, nem a tények független hitelesítése.
- `user_reported`: kézi forrásellenőrzési állítás. Az importált source_checked státuszt is erre gyengíti.
- `unverified`: nincs ellenőrizve. `rejected`: a rekord megmarad a naplóban, de a mozgáselemzésből kimarad.
- Hiányzó adat: null a tárolásban, „Nem elérhető” a felületen; nincs becsült odds vagy forgalom.
- A hírek és a mozgások időbeli kapcsolata mindkét irányban vizsgálható. A tényleges ok nincs automatikusan megállapítva. Az oddsmozgás nem manipuláció bizonyítéka.

## Tárolás és visszateszt

SQLite: alapértelmezetten `data/odds_detective.sqlite3`, felülírható az **ODDS_DB_PATH környezeti változóval**. Tartós kiszolgálón tartós kötetre mutasson. Streamlit Community Cloudon a helyi fájl túlélése újraindítás/újratelepítés esetén nem garantált. A modul nem szolgáltat külső felhőadatbázist: az éles, folyamatos archiváláshoz tartós lemezre telepített gyűjtő vagy külön adatbázis-integráció szükséges.

A JSON-export egy adott vizsgálat teljes mentése. A JSON-import legfeljebb 5 MB/10000 rekord, atomi és idempotens. Importáláskor a rögzítési idő új: egy utólag importált történelmi rekord nem jelenhet meg úgy, mintha korábban már ismerte volna az alkalmazás. Az as-of export csak a határidőig publikált **és rögzített** rekordokat adja a features mezőbe; az eredményeket külön result_labels mezőben őrzi meg, azokat ne használd bemenetként. Az export még nem stratégiai profit-visszateszt.

Rendes játékidős végeredmény kézzel, forrás-URL-lel és közlési idővel rögzíthető. Minden verzió megmarad; eltérő eredményeket külön ellenőrizni kell. A csapat- és dátumazonosításnál az UTC-napot használjuk.

A küszöb mind az előző, mind az első megfigyelt oddshoz képest abszolút **15%-nál nagyobb** relatív elmozdulás (számítási tolerancia: 1e-9 százalékpont). Nem az implikált valószínűség százalékpontos változása. Azonos időpontú eltérő árakat az elemzés kihagyja, a napló megőrzi. Különböző API-források és meccsfázisok nem alkotnak közös változási sorozatot.

## Háttérgyűjtés

A Streamlit nem futtat folyamatos gyűjtőt. Egyetlen odds-pillanatkép parancssorból (a `<…>` helyére ellenőrzött konfiguráció szükséges):

```sh
python odds_detective.py --match-id iberia-mjallby-2026-10-22 --sport '<soccer_sportkulcs>' --event-id '<esemenyazonosito>' --home '<API hazai nev>' --away '<API vendegnev>'
```

A kulcsot környezeti változóként állítsd be, ne parancssori argumentumként. Külső cronból ütemezhető, a szolgáltatói kvótához igazított időközzel. Betfair- és hírlekérés jelenleg a felületről indítható, nincs hozzá beállított háttérütemezés. A pusztán egyszeri vagy ritka pillanatképek nem tudják bizonyítani, melyik iroda lépett ténylegesen először.

## Tesztelés

```sh
python -m unittest discover -s tests -v
python -m compileall -q .
```

A teszt-fixture-ök mesterséges adatai kizárólag memóriabeli tesztadatbázisba kerülnek, nem az éles vizsgálatba. A csomag ellenőrzésekor 11 teszt ment át (adatimport, küszöb, időbélyeg, Exchange, visszateszt és eredeti modell). Streamlit-futtatás, böngészős ellenőrzés és éles API-hívás nem volt elvégezhető ebben a környezetben a függőségtelepítés/hálózat korlátozása és API-hozzáférések hiánya miatt. A GitHub-kódtár és a futó alkalmazás nincs automatikusan frissítve.


## Kísérleti Exact Score Hunter – csapaterősség

A baseline marad az alapértelmezés. A `poisson_model.py` a main változatlan
`becsles`, `goltabla`, `pontos_eredmenyek` függvényeit tartalmazza; a Streamlit
ugyanezeket importálja, a `becsles` visszatérése változatlan öt elem.
A közös új belépési pont: `team_strength.predict(snapshot, home, away, config)`.
A felület és a párosított visszateszt ezt használja.

A core helyszínfüggő támadó/engedettgól-paramétereket közösen illeszt, súlyozott
Poisson-likelihood és ridge alapján. `a>0` erősebb támadás, `d>0` több engedett gól,
tehát gyengébb védekezés. Alapérték: felezési idő 90 nap, ridge 5, extra ridge 10;
a súlyok nincsenek újranormalizálva. A determinisztikus koordináta-Newton
backtrackinget használ; a teljes gradiens maximum abszolút értéke legfeljebb
1e-8, legfeljebb 500 iteráció. Kis lépés önmagában nem konvergencia.
A baseline-hoz képest a teljes korrekció 0.75–1.25 arányra korlátozott.
A nyers core/extra hatás és a korlát külön látható; hibánál baseline fallback,
indokkal. Nincs új futtatási függőség.

Az új modulok: `asof_features.py` (rekordok, snapshotok, extra transzformációk),
`team_strength.py` (modell, scaler/extra tanítás), `correct_score_backtest.py`
(párosított értékelés, CLI). Egyetlen ligán/idényen belül dolgoznak.

### Időbeli szerződés

- `historical_results_replay`: csak a célmeccs és a cutoff UTC-napja előtti
  rendes játékidős befejezett eredmények. A dátumos CSV-ből nem gyártunk
  kezdési/publikálási/rögzítési időt. A CLI napi éjféli cutoffja értékelési
  határ, nem állított tényleges kezdés. Ez retrospektív eredmény-visszateszt,
  nem korabeli adatarchívum bizonyítéka; utólagos forrásjavítást nem zár ki.
- `strict_asof`: kizárólag ismert kezdés/befejezés és ellenőrzött bizonyíték;
  effective_at, published_at, captured_at mind szigorúan cutoff előtti.
  Egyenlőség kizárt. A verziók megmaradnak; a késői import/javítás nem ír múltat.
  A jelenlegi dátumos CSV és mai FPL-pillanatkép ehhez elégtelen.

A snapshot a célmeccs labeljét nem tartalmazza. A hash csak a kiválasztott
snapshotból készül, jövőbeli rekord nem része. Minden előrejelzés cutoffot,
snapshot-/config-hash-t, modellverziót, mintaszámot és fallback-indokot ad.
A core illesztés cache-e cutoffhoz, kiválasztott rekordokhoz és confighoz kötött;
azonos napi meccsek/ablációk ugyanazt az illesztést használják. Az Odds-nyomozó
UTC-napjait, adatbázisát és API-kvótakezelését nem módosítja.

### Extra adatséma és archívumstátusz

Az immutable `Evidence`, `ExtraStat`, `Match`, `Request` rekordok pontos
mezői az `asof_features.py` fájlban találhatók. Kötelező a szolgáltató,
rekordazonosító, verzió, raw-hash, ellenőrzési státusz, három UTC-időbélyeg,
mértékegység, definíció, nevező és lefedettség. Ismeretlen érték `None`.

- xG: `total_xg_for/against`, `xG/match`, `total_xg_v1`, nevező `match`.
  Pontrúgással együtt kizárólag `open_xg_for/against` / `open_xg_v1` használható;
  a pontrúgás külön `set_xg_for/against` / `set_xg_v1`. Ligaátlaghoz simított
  logarány, öt mintameccses prior. Nulla ligaátlag ismeretlen/inaktív.
- Stílus: `ppda`, `pressured_losses`, `counter_for/against`, a kódban rögzített
  szolgáltatói definícióval és nevezővel. Liga-standardizált pressing×labdavesztés
  és kontra×engedett kontra interakció; hírszöveg nem numerikus feature.
- Játékos: célmeccshez kötött `player_minutes`, `player_unavailable`,
  `player_att/def`, `player_replacement_att/def`, pozíció és játékosazonosító.
  Definíció `higher_is_better_v1`, nevező `pre_match`; a rating nagyobb értéke
  jobb teljesítmény. Percek előzetesen várhatók; kiesési valószínűség csak
  igazolt 0 vagy 1. FPL chance és tényleges lejátszott perc nem bemenet.
  Hiányzó helyettes/rating/percek esetén a veszteség ismeretlen.

A szolgáltatókat/egységeket nem keverjük. A tanítóidőszakból illesztett scaler
[-3,3]-ra vág; ismeretlen érték numerikusan 0, külön ismeretlenségi jelzővel.
A hiányjelző nem kap rejtett koefficienst. Teljesen hiányzó blokk hatása nulla.
Az extra ridge-regresszió rögzített, saját múltból becsült core offsetet használ;
200 időhelyesen értékelhető tanítómeccs alatt nincs aktív extra modell.
A tanítási artifact megőrzi a scaler-paramétereket, koefficienseket,
feature-sémát, határidőt és tanítási hash-t. Nincs kézzel kiosztott éles β.

**Nincs bekötött valós xG-, pontrúgás-, stílus- vagy játékosarchívum.**
Az interfész és a szintetikus tesztek nem jelentenek éles adatkapcsolatot vagy
igazolt javulást. A felületen ezért csak baseline/core választható.
Strict archívumok és extra modellek programozottan adhatók át; a CLI jelenleg
csak a dátumos eredmény-CSV replayét támogatja. Automatikus hiperparaméter-keresés
nincs; a konfigurációt a mérés előtt rögzíteni kell.

### Visszateszt UI nélkül

Saját, jogszerűen beszerzett Football-Data CSV-vel:

```sh
python correct_score_backtest.py /path/E0.csv --season 2025/26 --output backtest-report.json
python -m unittest discover -s tests -v
python -m compileall -q .
streamlit run streamlit_app.py
```

A JSON tartalmazza a bemeneti fájl SHA256-át/méretét, rekordhash-t, futásidőt,
60/20/20 egyedi dátumos határokat, párosított denominátorokat, kihagyási és
fallback-okokat, feature-lefedettséget, top-1/top-5 találatot és becsült
lefedettséget, stabil log-PMF NLL-t, 1X2 Briert, Wilson-intervallumokat és
napcsoportos páros bootstrap NLL-intervallumot (2000 újraminta, seed=42).
Abláció: baseline, frissesség, core, külön extra blokkok, teljes konfiguráció.
A visszateszt és bootstrap a felületen csak gombnyomásra indul.

200-nál kevesebb érintetlen tesztmeccs vagy hiányzó extra archívum esetén a
bizonyíték elégtelen. Aktiválás csak negatív teljes NLL-intervallum és nem romló
Brier esetén javasolható; automatikus alapértelmezés-váltás nincs.
Az Ipswich–Nottingham 1–1 felhasználó által jelzett top-1 találat, időbélyeges
modellnapló nélkül nem hitelesített előrejelzés; nem hangoltunk rá.

Az aktuális ellenőrzések és korlátok: [docs/VALIDATION.md](docs/VALIDATION.md).
