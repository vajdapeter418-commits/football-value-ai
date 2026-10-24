# Előzetes adatok archiválása – első adatkapcsolat

2026. október 24. Alap: PR #4, `90031b60a17329560deef0f94078d6df6ba9645e`.

Az öt idényes mérés nem igazolta a core fölényét. Ez a változás ezért **adatgyűjtést készít elő**, nem újabb esélykorrekciót: a baseline, a Poisson-modell és a Streamlit-felület számítása változatlan.

## Ellenőrzött adatforrások

| Forrás | Ellenőrzött lehetőség | Korlát és döntés |
| --- | --- | --- |
| FPL nyilvános API | A közvetlen próba 20 csapatot, 668 játékost, 380 mérkőzést adott a 2026/27-es idényből. Csapaterősségi mezők; játékosstátusz/hír, perc- és játékos-xG adatok. | Már elérhető, kulcs nélkül. Az archiváló ezt használja. Nem hitelesített sérüléslista/kezdő, nincs teljes korabeli állapotarchívum. |
| API-FOOTBALL | Hivatalos dokumentációban liga/idény lefedettség, meccshez kötött injuries, fixture-statisztika. Free csomag: napi 100 kérés, idénykorlátozással. | A felhasználónak van regisztrációs visszaigazolása, de ez nem bizonyít aktív csomagot/2026-os lefedettséget. Szerveroldali kulcs nincs ebben a környezetben. Csak egykéreses lefedettségi adapter készült; élő auth/kvóta/xG-tartalom nem ellenőrzött. |
| StatsBomb Open Data | Nyilvános eseményadatok kutatáshoz. A competitions és matches fájlok alapján a Premier League 2015/16 380 meccses listája elérhető. | Más korszak; a mérkőzéslista megléte nem minden eseményfájl teljes xG-lefedettségének bizonyítéka. Következő offline xG-kutatási jelölt, a mai PL meccseket nem fedi le. A közlésnél a szolgáltató attribúciós feltételeit alkalmazni kell. |
| Sportmonks | Dokumentált csapat-/játékos-xG végpontok. | Az xG külön fizetős kiegészítő. Nem választottuk az első, ingyenesen kipróbálható lépéshez; nem történt előfizetés. |

Források (ellenőrizve 2026-10-24):

- https://fantasy.premierleague.com/api/bootstrap-static/
- https://fantasy.premierleague.com/api/fixtures/
- https://fantasy.premierleague.com/help/faqs
- https://www.api-football.com/news/post/how-to-get-started-with-api-football-the-complete-beginners-guide
- https://www.api-football.com/pricing
- https://github.com/hudl/open-data
- https://github.com/hudl/open-data/blob/master/data/competitions.json
- https://github.com/hudl/open-data/blob/master/data/matches/2/27.json
- https://docs.sportmonks.com/v3/endpoints-and-entities/endpoints/expected-xg

## Használat

Csak standard Python-könyvtárak szükségesek. Egy kézi FPL-pillanatkép két GET-kéréssel:

```sh
python prematch_archive.py fpl --season 2026/27
```

Alapértelmezett fájl: `data/prematch_archive.sqlite3`; külön a nyomozó adatbázisától. Felülírható `PREMATCH_ARCHIVE_DB` környezeti változóval vagy `--db` argumentummal:

```sh
python prematch_archive.py --db /persistent/prematch.sqlite3 fpl --season 2026/27
```

Az API-FOOTBALL kulcsa kizárólag a szerver `API_FOOTBALL_KEY` környezeti változójába kerüljön, ne chatbe, kódba, URL-be vagy parancssori argumentumba. A kulcs nélküli parancs hálózati hívás nélkül leáll. Beállított kulccsal egy GET-kérés ellenőrzi és archiválja a liga/idény lefedettségét:

```sh
python prematch_archive.py coverage --league 39 --season 2026
```

Az adapter elutasítja a szolgáltatói `errors` választ (HTTP 200 mellett is), a hiányzó liga/idényt és a hiányos lapozott választ. Az `injuries=true` nem garantál minden meccshez teljes listát és nem igazolja az xG meglétét. Ez a parancs még nem tölti le a sérüléseket vagy az xG-t.

Nincs beállított cron/háttérgyűjtés vagy Streamlit-gomb. A lokális SQLite tartós szerveren tartós köteten fusson; egy kézi pillanatkép önmagában nem folyamatos archívum. A `data/` könyvtár már gitignore-olt: valódi válaszok nem kerülnek a GitHubra.

## Időbeli és szemantikai szerződés

- Egy bundle csak mindkét FPL-válasz sikeres letöltése és közös csapat-/meccsazonosító- és idényellenőrzés után kerül mentésre. Részleges hiba nem hagy részleges bundle-t.
- Minden nyers válasz külön UTC `fetched_at` időt és SHA-256 ellenőrző összeget kap. Az append-only mentési interfész új megfigyelést ír, a régit nem módosítja. Nincs utólagos, régi rögzítési időt állító importparancs.
- `available_at` legalább a helyi mentés ideje. A régebben letöltött bájtok későbbi betöltése sem válik korábban ismertté. A cutoffos olvasás szigorúan `available_at < cutoff`; egyenlőségnél kizárás. A bundle a második kérés elkészültéig sem teljes.
- Forrásoldali teljes-válasz publikálási idő nincs: `published_at=null`. A HTTP Date és az egyes hírek news_added mezője nem helyettesíti ezt. A későbbi adatok nem jelenhetnek meg egy korábbi lekérdezésben. A hash sérülést jelez, de nem külső hitelesítés.
- `status=observed_snapshot_only`, `model_eligible=false`. A meglévő strict `Evidence` szerződéshez nem gyártunk publikálási időt; az archívum nem ad közvetlen ExtraStat-ot vagy λ-korrekciót. Egy későbbi, külön validált observed-asof adatpolitika dönthet a használatáról.
- FPL játékos-xG nem automatikusan csapat-xG. A játékosok xG_conceded értékeit nem szabad csapat-xGA-ként összeadni. A szezonösszeg és a jelenlegi csapathoz rendelés átigazolásoknál különösen nem jelent meccshez kötött, tiszta csapatstatisztikát.
- A nyers `minutes` korábbi teljesítményadat, nem előre várt játékperc. A következő fordulós játékesély nem kezdési esély vagy automatikus hiányzási valószínűség. A hiányzó hír nem bizonyítja, hogy valaki bevethető; a team strength mező nem várható gólszám.
- Az endpointok HTTPS-allowlist alapján érhetők el, redirect követés nincs. Hiba esetén sem kulcs, sem választest nem kerül naplóba. Nincs automatikus ismétlés és nincs kvótát fogyasztó UI-újrarajzolás.

## Ellenőrzés és nyitott pontok

Nyolc új offline teszt: cutoff egyenlőség/jövő/késői import; ismeretlen publikálási idő és nyers játékosesély megőrzése; részleges capture elutasítása; atomi rollback és korrupció; idény/ID-kontraktus; kulcs nélküli nulla kérés; API-hibák/lapozás/lefedettség; idegen endpointok tiltása. A teljes csomag 34 tesztből áll. Az aktuális saját futás eredménye a PR leírásában szerepel.

Élő FPL CLI-próba sikerült: első bundle, 20 csapat / 668 játékos / 380 fixture, model_eligible=false. Az API-FOOTBALL élő ellenőrzése kulcs hiányában nem történt meg. A felületi megjelenítés, az ütemezett tartós gyűjtés, a fixture-enkénti xG-kinyerés és a tanult sérüléskorrekció további feladat; ezeket ez a változás nem állítja késznek.

A PR #4-re épülő külön draft PR, bázisa a `feature/exact-score-team-strength` ág. A PR #4 jóváhagyását/összeolvasztását nem helyettesíti. Sem a baseline, sem a korábban megmért core paraméterei nem változnak.
