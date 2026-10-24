# Pontoseredmény-kalibrációs kísérlet – 2026-10-24

**A hőmérséklet-kalibráció elkészült és lefutott, de nem igazoltunk megbízható javulást. A baseline marad éles.** A modul külön, opcionális kutatási kód; a meglévő előrejelzési útvonalak nem importálják és nem használják.

## Előre rögzített, időrendi eljárás

A helyi protokoll az illesztés előtt készült: `TEMPERATURE_EXPERIMENT_PLAN.md`. Az előző hibadiagnózis ismert volt, ezért ez eleve feltáró vizsgálat. Bemenet az öt idény (2020/21–2024/25) már látott, változatlan baseline-előrejelzés-CSV-je, SHA-256: `9a565df75e791b90ea6356cec1a15507de546554176dca402fb882748a03f486`. Új adatot nem töltöttünk le, a modell vagy a csapaterősség paramétereit nem hangoltuk.

A közös pontoseredmény-tábla transzformációja Q_T(h,a)=P(h,a)^(1/T)/ΣP^(1/T), T∈[0.5,2]. A normalizálás log-sum-exp-pel történik a baseline 0..100 gólos tartományán; a független margók miatt két egydimenziós normalizálás elegendő. Ezután az 1X2 esélyeket ugyanebből a közös eloszlásból összegezzük. A transzformált eloszlás már nem általában Poisson: az eredeti lambdákat nem nevezzük át új várható gólszámnak. A visszaadott `expected_goals` a transzformált margók tényleges várható értéke.

Idényenként az eredeti 60/20/20 dátumblokkok maradtak: T-t kizárólag a development-rész pontoseredmény-NLL minimumára illesztjük. Determinisztikus 40 iterációs aranymetszés, a végpontok és T=1 külön jelöltek. Legalább 60 tanítópélda kell; kevesebb adatnál identity. A development-rész utáni validáción csak alacsonyabb NLL és nem romló 1X2 Brier esetén fogadjuk el a jelöltet a későbbi végső blokkra; különben T=1.

Az artifact dátumhatárai ellenőrzöttek: a fit kizárja a cutoff napját és a jövőt a tanítási hash számítása előtt; az alkalmazás tiltott, ha a tanítás vagy a kiválasztás utolsó napja nem korábbi a célmeccs napjánál. A végső blokkra kiválasztott artifact a validáció végdátumát is rögzíti, mert maga a kiválasztási döntés is adatból tanult. A jelentés az inputhash-t, tanítási hash-t, verziót és dátumokat is megőrzi.

## Eredmény a már látott végső blokkok 368 meccsén

| Változat | Pontoseredmény NLL ↓ | 1X2 Brier ↓ | Top-1 találat | Top-5 találat | Átlagos top-1 esély | Átlagos top-5 esély |
|---|---:|---:|---:|---:|---:|---:|
| Eredeti baseline | 3.057679 | 0.552401 | 39/368 | 167/368 | 11.82% | 47.81% |
| Minden idényben tanított T, szűrés nélkül | 3.057877 | 0.552662 | 39/368 | 167/368 | 10.83% | 44.66% |
| Validáció alapján kiválasztott T vagy identity | 3.055882 | 0.552420 | 39/368 | 167/368 | 11.37% | 46.43% |

A kiválasztott eljárás NLL-különbsége a baseline-hoz képest -0.001797, 95%-os napcsoportos bootstrap intervalluma [-0.008188; +0.004402]. Ez átfedi a nullát. A Brier-különbség +0.00001892, tehát ezen a mintán minimálisan romlik. A szűretlen tanított jelölt NLL-je és Brierje is kissé rosszabb a baseline-nál.

A tényleges top-1 arány 10.60%, a baseline becsült átlaga 11.82%, a kiválasztott változaté 11.37%. Ez közelebb van a tényleges összesített arányhoz, de önmagában nem teljes kalibrációs vizsgálat és nem bizonyított általános javulás. Top-5-nél a tény 45.38%, a becslés 47.81%-ról 46.43%-ra változik. Ezek leíró eredmények ugyanazon már látott meccseken.

A top-1/top-5 találatszám és a sorrend minden értékelt meccsen változatlan maradt. A kalibráció önmagában nem növeli a pontos találatok számát.

## Idényenkénti döntések

| Idény | Development n | Validation n | Későbbi n | Illesztett T | Választott T | Későbbi NLL eltérés | Későbbi Brier eltérés |
|---|---:|---:|---:|---:|---:|---:|---:|
| 2020/21 | 181 | 65 | 69 | 1.079135 | 1.079135 | +0.004750 | -0.000488 |
| 2021/22 | 173 | 66 | 81 | 1.121359 | 1.121359 | -0.002650 | +0.000365 |
| 2022/23 | 172 | 75 | 73 | 1.035332 | 1.035332 | -0.010610 | +0.000151 |
| 2023/24 | 158 | 73 | 79 | 1.184484 | 1.000000 | +0.000000 | +0.000000 |
| 2024/25 | 180 | 74 | 66 | 1.167009 | 1.000000 | +0.000000 | +0.000000 |

A validáció az első három idény jelöltjét fogadta el, a 2023/24-es és 2024/25-ös jelöltet elutasította. Egy validáción elfogadott változat később is romolhat: például a 2020/21-es NLL és a 2021/22-es Brier ezt mutatja. Nem választottunk utólag más T-t ezek javítására.

## Ellenőrzések és korlátok

**40/40 teszt sikeres, 7.037 s**, nincs skip; compileall sikeres. Ez a kísérleti ág teljes csomagja, nem a main 52 tesztjének újrafuttatása. Az öt új kalibrációs teszt ellenőrzi az identity-egyezést, a teljes valószínűségi tömeget, a nem egységnyi T kézi valószínűségarányát, a rangsort/holtversenyt, az 1X2 újraszámítását, a stabil NLL-t, a célmeccs napi/jövőbeli tanítórekordok kizárását, a dátumhatárok tiltását, a determinisztikus illesztést, az elégtelen tanítómintát és az érvénytelen bemeneteket. Az illesztés fejlesztési NLL-je nem rosszabb a T=1 jelöltnél.

Az adatpolitika továbbra is historical_results_replay: a végleges eredményadatok akkori elérhetőségét és későbbi javításait archívum nélkül nem igazolja. A most használt végső blokkokat már láttuk az előző vizsgálatokban. Ezért még egy kedvező eredmény sem lenne új érintetlen teszt vagy élesítési bizonyíték.

A 2000, seed=42, idény+dátum szerinti páros bootstrap leíró bizonytalanságot ad; nem kezeli teljesen a napok közötti függőséget. A teljes pontoseredmény-tábla 0..100 gólos támogatása és a T tartomány rögzített, nem utólag választott.

**Nincs merge/deploy, alapértelmezett modellváltás vagy UI-bekötés.** A PR #4 draft marad. A main napi keresője, pontoseredmény-visszatesztje és API-diagnosztikája változatlan. A külön modul normál használatban nem fut le magától és nem kér le adatot.

## Megismétlés

```sh
PYTHONPATH=. python research/evaluate_score_calibration.py /path/to/predictions.csv --output /path/to/temperature.json
python -m unittest discover -s tests -v
python -m compileall -q score_calibration.py research tests
```

A futtató a rögzített inputhash eltérésekor leáll. Az előrejelzés-CSV a korábbi `research/validate_team_strength.py` futtatásával reprodukálható, a forrásfájlok a `TEAM_STRENGTH_DATA_SOURCES.json` manifest alapján ellenőrizhetők. Minden illesztett és kiválasztott artifact, validációs és későbbi metrika: `TEMPERATURE_EXPERIMENT_20261024.json`.

Következő döntési pont: a meglévő baseline fenntartása és egy valóban eddig nem használt későbbi időszak előre rögzített értékelése. A most látott adatokon újabb T-t vagy elfogadási küszöböt keresve nem lehet független bizonyítékot előállítani. Ilyen új méréshez külön rögzíteni kell az adatidőszakot és az előrejelzések készítéskori állapotát; automatikus gyűjtést ez a feladat nem indít.
