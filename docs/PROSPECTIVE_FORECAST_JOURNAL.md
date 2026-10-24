# Előre rögzített pontoseredmény-napló – előkészítés

2026-10-24. Alap: main `e2610499a5934282e6c6cde97b5c56b27cd6c985`. A már látott történeti tesztek és kalibrációs kísérletek nem adnak új, független bizonyítékot. Ehhez a következő mérkőzések előtt ténylegesen elmentett előrejelzések kellenek.

**Ez a változás külön, kézzel indítható naplózási alap, nem aktív éles adatgyűjtés.** Nem módosítja a Streamlit oldalt, a baseline-t vagy a kalibrációt, és nem függ a PR #4-től. Nem indít hálózati kérést, időzítést vagy API-kulcs-olvasást. A meglévő `prematch_archive.py` szolgáltatói megfigyeléseket tárol; ez a külön modul a modell konkrét előrejelzését és bemeneti mintáját fagyasztja be, más táblában/adatbázisban.

## Mentett tartalom

- Premier League/idény, külső fixture-azonosító, a CSV-vel egyező hazai/vendég név, előre megadott UTC-kezdés.
- Saját szerveróra szerinti megfigyelési és rögzítési idő. Nem adható át visszadátumozó paraméter.
- A felhasznált CSV forráshivatkozása és nyers SHA-256-a; a ténylegesen felhasznált normalizált eredménysorok és külön hash-ük.
- A mainből változatlanul importált `becsles`, `goltabla`, `pontos_eredmenyek` függvények forrásának hash-e, modellverzió, lambdák, 1X2-esélyek, az öt pontos tipp és valószínűségük, mintaszámok.
- Az előző naplóbejegyzés hash-e és a teljes aktuális bejegyzés hash-e. A JSON-export tartalmazza a láncot, darabszámot és gyökérhash-t.

A forrásreferencia az adott idény Football-Data E0 CSV-címe. A helyben átadott CSV-t most figyeljük meg; a forráshivatkozás önmagában nem igazolja a fájl szolgáltatói hitelességét. A kézzel átadott meccsazonosság és kezdés sem függetlenül hitelesített szolgáltatói rekord. Ezért a rekord `locally_observed_csv_not_independently_authenticated` állapotot kap. A protokoll és későbbi felületi bekötés előtt valós fixture-forrással össze kell ellenőrizni.

## Időhelyesség és megőrzés

A célmeccsnek több mint öt perccel később kell kezdődnie a rögzítésnél; ezt a számítás után, a tranzakcióban is újra ellenőrizzük. Visszafelé ugró óra, múltbeli vagy túl közeli kezdés esetén nincs mentés.

Csak a kiválasztott idény befejezett CSV-eredményei kerülhetnek a mintába, és dátumuk szigorúan kisebb a megfigyelés UTC-napjánál és a célmeccs UTC-napjánál is. Az aznapi meccsek mind kizártak. A nyers fájl hash-e dokumentációs célú; a mintahash és becslés csak a jogosult korábbi soroktól függ. Legalább 60 korábbi ligameccs és 3 megfelelő hazai/vendég csapatmeccs kell, ugyanúgy, mint a visszatesztnél. Dupla történeti fixture-sor hibát okoz, nem növeli a mintát.

Egy külső fixture-azonosítóhoz, illetve egyazon idénybeli hazai/vendég pároshoz csak az első mentett előrejelzés tartozhat. Átnevezett azonosítóval vagy új kezdési idővel sem írható át. Halasztást, téves azonosítót és törlést külön későbbi kimeneti státusszal kell kezelni; a mostani modul az eredeti naplót őrzi, eredményt nem könyvel és kivételt nem tüntet el.

Az SQLite `BEGIN IMMEDIATE` tranzakció sorba rendezi a párhuzamos mentéseket. UPDATE/DELETE trigger védi a véletlen módosítást. Export előtt a lánc és mintahash ellenőrzött, egyetlen olvasási tranzakcióban. Az export nem írhatja felül ugyanazt az adatbázisfájlt.

Ez **nem független időbélyeg-szolgáltatás vagy támadóval szemben megváltoztathatatlan tároló**: aki a gép óráját/adatbázisát korlátlanul módosíthatja, újraírhatja a teljes láncot vagy levághatja a végét. Az exportokat külön, tartós, verziózott helyre kell menteni és az akkori hash-t külön megőrizni. A Streamlit Cloud helyi SQLite-fájlja elveszhet; önmagában nem elegendő a kutatási archívumhoz.

## Kézi használat fejlesztői környezetben

Az alkalmazás meglévő Streamlit-függősége szükséges, mert a main modellfüggvényeit importáljuk; a modul importja nem indítja el az alkalmazás felületét vagy adatletöltését. A CSV és a fixture-adatok külön, ellenőrzött beszerzése előfeltétel.

```sh
python forecast_journal.py --db /path/to/forecasts.sqlite3 capture --csv /path/to/E0_2627.csv --fixture-id PROVIDER_ID --home "HOME_NAME" --away "AWAY_NAME" --season 2026/27 --kickoff "FUTURE_KICKOFF_WITH_TIMEZONE" --source-url https://www.football-data.co.uk/mmz4281/2627/E0.csv
python forecast_journal.py --db /path/to/forecasts.sqlite3 verify
python forecast_journal.py --db /path/to/forecasts.sqlite3 export --output /path/to/forecasts-export.json
```

A fenti nevek és kezdés helyőrzők, nem valódi meccsek. Nincs beégetett tesztmérkőzés vagy automatikus hívás. A telefonos felhasználónak ezt a CLI-t nem kell futtatnia; a következő integráció biztosíthat gombnyomásos mentést az ellenőrzött mérkőzésválasztóból.

## A következő, valóban új mérés elfogadási terve

A gyűjtés még nem indult. Az alábbi tervet aktiválás előtt véglegesíteni kell, az akkor ismert fixture-listával és működő tartós exporttal együtt.

1. A rögzített baseline legyen a referencia. A kalibráció és a csapaterősség kísérleti marad. Bármely jelölt algoritmust/paramétert a mérési időszak előtt külön hash-sel és dátummal rögzíteni kell.
2. A kezdés legkorábban 2026-10-25, illetve a tényleges naplózási aktiválás utáni első teljes budapesti naptól lehet; korábbi meccs nem pótolható utólag. A bevont időszakot és meccslistát az eredmények előtt rögzítjük. Az első 200 időrendben sorra kerülő jogosult Premier League-fixture legyen a tervezett cél; a kimaradásokat, halasztásokat és hibákat is kötelező naplózni. Nem választhatjuk utólag csak a sikeresen mentett vagy eltalált meccseket.
3. A mentés csak ellenőrzött kezdés előtt történhet. Az eredményeket később, külön forrásból kell csatolni; hosszabbítás/büntetők kizártak. A naplóbejegyzést az eredménycsatolás nem módosíthatja.
4. Előre kijelölt kiértékelési ponton NLL, 1X2 Brier, top-1/top-5 találati arány, becsült esélyek, napcsoportos bizonytalanság és teljes lefedettségi/kimaradási kimutatás kell. Addig nincs menet közbeni hangolás vagy kedvező ponton való leállítás. Elégtelen mintán a következtetés elégtelen, nem siker.
5. A végleges kezdőnap, ellenőrzött fixture-manifest, tartós mentési útvonal, felületi bekötés, eredménycsatoló/értékelő és a tényleges gyűjtés indulásának igazolása még külön integrációs feladat. A mostani változás ezeket nem állítja késznek.

## Validáció

A jelenlegi main 52 tesztje és nyolc új naplóteszt együtt: **60/60 sikeres, 5.678 s**, nincs skip. Compileall és CLI `--help` sikeres. A tesztek ideiglenes adatbázist és mesterséges CSV-t használnak; nem készül éles próbaelőrejelzés.

Ellenőrizve: változatlan baseline-egyezés; kétbejegyzéses hash-lánc/export; aznapi és jövőbeli eredményinvariancia; múltbeli/közeli/naiv kezdés tiltása; duplikált meccs védelme megváltoztatott ID-val/kezdéssel is; SQL-felülírás/törlés tiltása és sérülésészlelés; tranzakciós óra-/kezdésellenőrzés és rollback; hibás forrás/dupla vagy elégtelen előzmény elutasítása; két párhuzamos mentésből pontosan egy bejegyzés.

A fejlesztés önálló draft PR mainre, PR #4 összeolvasztása nélkül. Nincs telepítés, módosult éles tipp, háttérgyűjtés vagy jövőbeli eredményből előállított próbateljesítmény.
