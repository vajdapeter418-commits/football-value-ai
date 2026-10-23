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


## Napi mérkőzéskeresés és előzmények

Az Oddsmozgás-nyomozó új munkamenetben a **Napi mérkőzéskeresés** nézettel indul.
A dátum az aktuális Europe/Budapest naptári nap; a kézi dátumválasztás az aktív
munkamenetben megmarad, napváltáskor is. Új böngészőmunkamenetben ismét a mai nap
az alapérték. A kezdési időpontok budapesti idő szerint jelennek meg, a nyári/téli
időszámítás figyelembevételével.

A bajnokságokat és a kiválasztott bajnokság mérkőzéseit a betöltés / frissítés
gombok kérik le. A dátumváltás és a felület újrafutása a munkamenetben már betöltött
listát használja, nem indít új API-hívást. Az API csak élő/közelgő eseményeket adhat;
a kiválasztott napra hiányzó találatot nem pótoljuk kitalált adatokkal. Az oddsok
lekérése továbbra is külön, felhasználói gombnyomáshoz kötött, kreditet fogyaszthat.

A napi listából létrehozott vizsgálat automatikusan megnyílik a **Mentett vizsgálatok /
előzmények** nézetben. A kézi létrehozás is az új vizsgálatot választja ki.
A mentett vizsgálatok dátuma továbbra is UTC-nap: API-eseménynél ezt a kezdési
időpontból számítjuk, ezért éjfél körül eltérhet a keresés magyar napjától.
A korábbi vizsgálatok és bizonyítékok változatlanok; nincs adatbázis-migráció.
