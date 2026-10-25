# Piaci nyomozó (#12)

## Kiinduló állapot és szűk terv

A main vizsgált commitja: `b143b8d68fb71f66e47019e915356704a25aae8c` (PR #11, mobil naplóbelépés). Átnézett modulok: Streamlit navigáció, baseline, oddsnyomozó, `forecast_journal.py`, `forecast_cloud.py`, `forecast_journal_ui.py` és tesztjeik. A privát napló jelszavas hozzáférést, privát repository-ellenőrzést, hash-láncot, append-only előzményt, fájl-SHA alapú ütközésvédelmet és commit-visszaigazolást használ. Ezek a fájlok változatlanok maradnak.

Nyitott fejlesztések: #4 draft, mainre célzó kísérleti csapaterősség/kalibráció, régi bázison (`82bc979`); #5 draft, a #4 ágára épülő előzetes archívum/API-próba. Állapotuk, leírásuk és módosított fájllistájuk ellenőrizve. Nem integráljuk őket; a main jelenlegi API-próbája és naplója megmarad. Közös későbbi integrációs pont a `streamlit_app.py` navigációja.

Terv: (1) külön, privát, append-only megfigyelési/eredmény/protokoll archívum; (2) forrással jelölt kézi és atomikus CSV-import; (3) külön mobilon is egyoszlopos kutatási nézet; (4) rögzített szabályú időrendi visszateszt, kontrollok és bizonytalanság; (5) regressziós és runtime tesztek, külön feature PR mainre, automatikus merge nélkül.

## Használat és tárolás

Az oldalsáv **Piaci nyomozó** nézete ugyanazt a szerveroldali `FORECAST_ARCHIVE_TOKEN`, `FORECAST_ARCHIVE_REPOSITORY`, `FORECAST_JOURNAL_PASSWORD` konfigurációt és változatlan belépési ellenőrzést használja, mint a Tippek naplója. A token kizárólag a szerveren marad. A nyilvános forráskódtár nem lehet adatarchívum.

A piaci adatok külön `market-research` ágon, `archive/market-research.json` fájlban vannak. A `forecast-archive` ág és `archive/forecast-journal.json` érintetlen. Nincs migráció, törlés vagy automatikus élesítés. Első alkalommal a külön archívum létrehozása gomb használható. Sérült vagy nem hozzáférhető archívumnál nem ajánlunk nullázást. Az import és az eredményrögzítés csak privát repository + helyes jelszó után érhető el.

Minden mentés frissen betölti és ellenőrzi az előzményt; kizárólag annak folytatása fogadható el. GitHub PUT a betöltött fájl-SHA-val történik, nincs vak retry. Siker csak commit-visszaigazolás után. Hálózati hiba után előbb frissíts: egy bizonytalan válasz mögött a commit akár létre is jöhetett. A JSON biztonsági mentése letölthető; helyi gép/Streamlit fájlrendszer elvesztése nem törli a felhőben visszaigazolt adatot. Megfigyelés, eredményjavítás és kutatási protokoll külön hash-láncot alkot. A piaci fájl legfeljebb 700000 bájt; rotáció még nincs. A régi tippnapló korlátai nem változnak.

Az alkalmazás nem tudja a GitHub-tulajdonos vagy a szerveróra teljes hozzáférésével történő történethamisítást kizárni. A hash és a GitHub-verziózás integritásellenőrzés, nem független időbélyeg-hitelesítés.

## Kézi bevitel és CSV-séma

A kézi űrlapon külön mezők vannak a csapatokra, sportágra, piacra, handicap/total vonalra, eredeti irodára, közlőre, forrásra és UTC-időkre. A kimenetelek a form előtt változtathatók. Minden oldalon külön tickets/handle mező van, az üres érték **nem elérhető**. A százalékok nem kerekítődnek egészre. Komplementert soha nem képzünk automatikusan: csak kétszereplős piacon, ellenoldali közölt érték és pontos 100%-os összeg mellett jelölhető számítottként. Az aktuális odds külön kimeneteli mezőkben adható meg; további odds-idősor és hírek strukturált JSON-ként vihetők be. Teljes, egymást kizáró és kimerítő piac szükséges, pl. 1X2-nél a döntetlen is.

CSV: UTF-8 (BOM elfogadott), egyetlen fejléc: `observation_json`. Minden további sor egy JSON-objektum szabályos CSV-idézőjelezéssel. Maximum 500 rekord, 2 MiB; bármely hibás rekord az egész importot elutasítja, korábbi adatok változatlanok. A felületen üres CSV letölthető. Szerveridő/prospective státusz nem importálható. Történeti adat megőrizhető, de késői bevitelként nem kerül az előzetes visszatesztbe.

A JSON-megfigyelés mezői:

| Mező | Jelentés |
|---|---|
| fixture_id, home, away, sport | Stabil, whitespace nélküli azonosító/sport és csapatnevek |
| market, line | Piac és külön handicap/total; vonal nélkül `none` |
| bookmaker | Eredeti iroda; a splits és az odds azonos irodára és piacra vonatkozik |
| kickoff | Időzónás ISO-idő, pl. `2026-11-01T12:00:00Z` |
| outcomes | Kimenetelek különböző neveinek listája |
| source | Az alábbi forrásobjektum |
| shares | Kimenetelenként tickets, tickets_origin, handle, handle_origin |
| odds | Időrendben rendezett teljes odds-pillanatképek listája |
| news | Külön időbélyeges csapathír-lista |
| hypothesis, explanation | Külön kutatási feltevés és magyarázat (üres szöveg elfogadott) |

`shares` minden kimenetelt tartalmazzon. Egy oldal alakja: `{"tickets":null,"tickets_origin":"unavailable","handle":null,"handle_origin":"unavailable"}`. Szám esetén 0..100; eredet `reported` vagy `calculated_complement`. Teljes közlés összege metrikánként 100%, részleges közlésé legfeljebb 100%. Nincs becsült dollárösszeg.

A **forrásobjektum** kötelező mezői: `publisher` (közlő oldal), `original_source` (eredeti adatforrás), `original_bookmaker`, `url` (HTTPS, beágyazott jelszó nélkül), `published_at`, `observed_at` (időzónás időpontok), `original_text` (eredeti közlés), `verification` (`manual_verified` / `unverified`), `permission` (`manual_reference` / `licensed_api` / `unknown` / `denied`), `fetch_status` (`manual` / `ok` / `not_available` / `error`). `licensed_api` esetén `license_url` is szükséges, HTTPS dokumentált jogosultsággal. A forrás publikálása nem lehet a megfigyelés után. Jövőbeli megfigyelés tiltott.

VSiN-en közölt DraftKings-adatnál `publisher=VSiN`, `original_bookmaker=DraftKings`, `bookmaker=DraftKings`. Ettől nem lesz két független minta. Circa csak tényleges Circa-eredet igazolásával jelölhető; a program az eredetazonosságot ellenőrzi, a tulajdonosi forrásnyilatkozat igazságát nem tudja függetlenül hitelesíteni. Ellentmondó, azonos időre jelentett splits nem kerül mérésbe.

Egy **odds-pillanatkép**: `at` (UTC-idő), `kind` (`opening`, `closing`, `12h`, `snapshot`), `prices` (minden kimenetel száma), `convention` (`decimal` / `american`, alapértelmezett decimal), `source` (teljes forrásobjektum, saját korabeli időbélyegekkel). Decimális odds >1; amerikai abszolút érték >=100. A mentés megőrzi az eredeti árakat/formátumot, kiszámolja a decimális oddsot, az overroundot (`Σ1/odds−1`) és a marginmentesített esélyt (`(1/odds)/Σ1/odds`). Hiányos piacból nem számol esélyt. `12h` jelölés: kezdés mínusz 12 óra ±15 perc. Az opening/closing címke ellenőrzött közlésből származó kézi jelölés; hiányzó pontot nem találunk ki. Az odds-időpontnak a kezdés előtt és a forrás megfigyelése előtt/azzal egy időben kell lennie.

Egy **hír**: `kind` (`injury`, `rotation`, `lineup`, `other`), `certainty` (`fact`, `assumption`), `text`, `source` (teljes saját forrás). A megfigyelés kezdés előtti legyen. Utólagos magyarázat az eredményrekordba tartozik.

A forrásellenőrzés nélküli/tiltott/hibás adat megőrizhető a privát tárban, de értéke nem jelenik meg az összehasonlító nézetben és nem jogosult a mérésre. A forrásfrissesség külön státusz; a visszateszt a **döntési időhöz**, nem a mai időhöz képest ellenőrzi. A UI aktuális frissességet mutat. Tickets-only piacnál külön figyelmeztetés, nincs kitalált handle vagy eltérés.

## Eredmény és kutatás

A befejezett meccs eredménye külön rekord: fixture/sport/piac/vonal, `actual_kickoff`, `ended_at`, `score` szöveg, `source_url`, `explanation`, `confirmed=true`, és minden kimenetelre `settlement`. Elfogadott elszámolás: win/loss/push/void/half_win/half_loss. Spread/ázsiai piacnál a rendes játékidő/hosszabbítás/handicap szabályt a rögzítő ellenőrzi és leírja. A program nem találja ki a végeredményből a speciális piac elszámolását. Javítás új rekord; mérés a megfelelő időhatárig ismert legújabb verzióval. A megfigyelés eredeti tartalma nem módosítható.

A kutatás rögzített, előre választható szabályokat mér, nincs automatikus tipp:

- baseline: a döntéskor ismert marginmentes esély szerinti favorit;
- movement: a legnagyobb pozitív marginmentes esélyváltozás, küszöb felett;
- gap: a legnagyobb handle−tickets **százalékpont** eltérés, küszöb felett;
- combined: a két előző szabály ugyanazt az oldalt választja;
- with_news: combined, és a cutoff előtt ismert, ellenőrzött tényszerű hír is van;
- high_handle / low_handle: a legnagyobb / legkisebb pénzarányú oldal külön, csak teljes handle-közlés és eltérő arányok esetén.

A hírteszt jelenléti szűrő: nem NLP vagy a hír irányát értelmező modell. A movement az első és utolsó cutoffig ismert teljes árat hasonlítja; az első pont nem feltétlenül valódi opening. A kijelző külön nevezi az odds **százalékos** változását, a splits-különbség és a marginmentes esélyváltozás **százalékpont**. Nem következtetünk sharp pénzre.

Döntési cutoff: a rögzített tervezett kezdés mínusz a választott óraszám. A szerver mentési ideje, a splits megfigyelése, az odds és saját forrásmegfigyelése, a hírek mind legkésőbb cutoffkor ismertek legyenek. Korábbra hozott tényleges kezdés esetén konzervatívan kizárunk, ha a választott horizon sérül; későbbi kezdés nem ad extra információt a régi cutoffhoz. Későbbi rekordoktól a korábbi kiválasztott jel nem változhat. Azonos iroda/piac/vonal/fixture legfeljebb egyszer szerepel; a közlőoldalak nem független minták. A fixture azonosítóhoz utólag eltérő csapat/tervezett kezdés nem rendelhető; halasztás miatti új kutatási epizódot külön stabil azonosítóval kell kezelni.

A tesztidőszak `[test_start, test_end)`; a korábbi mérkőzések fejlesztési mintaként külön szerepelnek, csak tesztkezdet előtt már ismert címkékkel. A későbbi címkék kizárólag kiértékelésre szolgálnak. A szabályokat a kód nem optimalizálja a teszten. Egy jövőbeli tesztperiódushoz a UI-n **előre rögzíthető protokoll**: paraméterek, teljes mintavételi manifest, jövőbeli dátumhatárok. A későbbi protokolljelentés ezeket változatlanul használja. Protokoll nélkül a jelentés kifejezetten feltáró történeti visszajátszás, nem igazolt érintetlen out-of-sample mérés. A manifest betartását és azt, hogy a kutató korábban mit látott, emberi ellenőrzésnek is igazolnia kell.

ROI: fix egy egység minden nem void választásra, rögzített decimális árral; win=odds−1, loss=−1, push=0, half_win=(odds−1)/2, half_loss=−0.5. Void nem része a nevezőnek; a push és félkimenetelek külön számlálódnak. A győzelmi arány teljes win/(win+loss), fél/push/void kimenetelek nélkül. A 95%-os intervallum 500 determinisztikus bootstrap-újramintavétellel, fixture-csoportok megőrzésével készül; 2 fixture alatt nincs intervallum. Baseline-különbség az adott szabály **azonos kiválasztott sorain** párosított. A jelentésben piaconként/vonalanként/irodánként, baseline-odds félpontos sávja, 0.01-re csoportosított overround és döntési horizon szerint külön kontrollcsoportok is szerepelnek. A sorok az ár-, forrás-, szerver-, döntési és eredményidőket megőrzik. Ezek leíró kontrollok, nem oksági bizonyítékok vagy teljes regressziós korrekció.

Mindig látható selection bias, több piac/szabály, 100 fixture alatti kis minta, eredeti irodák közös eredete és a fixture-bootstrap által nem lefedett időbeli függőség figyelmeztetése. A feltételes stratégiák nyers ROI-ja eltérő kiválasztott mintából nem tekinthető közvetlen javulásnak; ehhez a párosított különbség, kontrollcsoportok és valódi későbbi minta kell.

## Szándékos korlátok

Nincs élő tickets/handle API bekötve: bizonyítható jogosultságú szolgáltató nem áll rendelkezésre. A dokumentált API-eredetű export rögzíthető, de az alkalmazás nem hív tetszőleges URL-t és nem kezel kliensoldali szolgáltatói kulcsot. Nincs scraping vagy élőnek feltüntetett demo. Denver–OKC, Stanford–NC State és Iberia–Mjällby adatait nem vettük át; csak ellenőrzött eredeti forrás alapján vihetők fel. A tesztadatok kizárólag szintetikus fixture-ök a tesztkönyvtárban, a felhasználói nézet üres adatokból indul.

A JSON/CSV-bevitel strukturált, nagy idősorhoz tudatosan fejlettebb importútvonal. Nincs többfelhasználós ACL, automatikus eredményhitelesítés, pénzösszegbecslés, forrásoldali aláírás-hitelesítés vagy automatikus archívumrotáció. Nincs változás a Poisson/Exact Score képletekben, a meglévő adatokban vagy a privát napló szabályaiban.
