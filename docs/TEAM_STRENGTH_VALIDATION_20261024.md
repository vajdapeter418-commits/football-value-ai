# Csapaterősség: többidényes megismétlés és szezonkezdet

2026-10-24. Vizsgált modell: `90031b60a17329560deef0f94078d6df6ba9645e`, PR #4. **A baseline maradjon alapértelmezett; nincs aktiválási vagy összeolvasztási javaslat.** A modellkódot és paramétereit ez az ellenőrzés nem módosítja.

## Mérés és megismételhetőség

Az öt korábban kijelölt Premier League-idény (2020/21–2024/25) változatlan, már letöltött Football-Data eredmény-CSV-jén újrafuttattuk a teljes backtestet. Nem történt új adatletöltés, hiperparaméter-keresés, tesztidőszak-választás vagy modellhangolás. Az eredeti mérési terv SHA-256: `fb98b8f14a76bb145f2ee41cffbd0143e145fa02753f27382b85487df795b1ed`.

1900 bemeneti meccs, 1585 értékelt, 315 kihagyott. Minden idény külön, előző idényből átvitt statisztika nélkül indul. Jogosultság: 60 korábbi ligameccs és 3 megfelelő hazai/vendég csapatmeccs. Az egyedi napok szerinti 60/20/20 felosztás utolsó blokkjai együtt 368 értékelt meccset tartalmaznak. Ezek most már látott tesztadatok: az ismétlés reprodukció, nem új független bizonyíték. Az új részhalmaz-elemzések utólagos, leíró diagnosztikák, nem új érintetlen tesztek.

A négy modellmodul tartalmát újra beolvastuk GitHubról a rögzített commiton. A teljes újrafuttatás 105.05 s. Az eredeti és megismételt meccsenkénti `predictions.csv` bájtról bájtra egyezik; SHA-256: `9a565df75e791b90ea6356cec1a15507de546554176dca402fb882748a03f486`. A hordozható futtatóval a 2024/25-ös idény külön megismétlése is ugyanazokat a sorokat adta.

Rögzített beállítások: felezési idő 90 nap, ridge=5, extra_ridge=10, tolerancia=1e-8, legfeljebb 500 iteráció, a baseline lambdáihoz képest 0.75–1.25 korrekció. Extra adatblokkok inaktívak.

## Elsődleges eredmények

| Modell | Top-1 | Top-5 | Pontoseredmény NLL (kisebb jobb) | 1X2 Brier (kisebb jobb) |
|---|---:|---:|---:|---:|
| Baseline | 39/368 (10.60%) | 167/368 (45.38%) | 3.057679 | 0.552401 |
| Core csapaterősség | 38/368 (10.33%) | 171/368 (46.47%) | 3.050145 | 0.553931 |

Core–baseline NLL-különbség: -0.007535; 2000, seed=42, napcsoportos páros bootstrap 95%-os intervallum: [-0.028039; +0.012046]. Tartalmazza a nullát. A Brier +0.001529-cel romlik. Az előre rögzített feltétel (n>=200, teljes NLL-intervallum nulla alatt, nem romló Brier) nem teljesül. A frissesség-only összehasonlítás sem választható utólag éles győztesnek: ugyanezeken a már látott adatokon mértük.

| Idény | Értékelt/kihagyott | Teszt n | Baseline top-1 | Core top-1 | Baseline top-5 | Core top-5 |
|---|---:|---:|---:|---:|---:|---:|
| 2020/21 | 315/65 | 69 | 11 | 9 | 34 | 37 |
| 2021/22 | 320/60 | 81 | 8 | 8 | 35 | 35 |
| 2022/23 | 320/60 | 73 | 4 | 5 | 36 | 36 |
| 2023/24 | 310/70 | 79 | 8 | 8 | 33 | 33 |
| 2024/25 | 320/60 | 66 | 8 | 8 | 29 | 30 |

## Szezonkezdet és kevés csapatadat

A részhalmazok átfedhetnek, és nem használhatók modell-/küszöbválasztásra. Az első 100 meccs: idényenként dátum, majd stabil meccsazonosító szerinti első 100 fixture. Kevés adat: az előrejelzés előtt a két releváns helyszínspecifikus csapatmeccsszám minimuma 3–5. Egyik szűrés sem használja a célmeccs góljait.

| Utólagos diagnosztika | Értékelt n | Baseline top-1 | Core top-1 | Baseline top-5 | Core top-5 | Core–baseline NLL 95% |
|---|---:|---:|---:|---:|---:|---|
| Idényenként első 100 meccs | 185 | 15 (8.11%) | 19 (10.27%) | 77 (41.62%) | 80 (43.24%) | [-0.032559; +0.014055] |
| Legalább az egyik csapatnak csak 3–5 megfelelő meccse van | 299 | 27 (9.03%) | 30 (10.03%) | 123 (41.14%) | 130 (43.48%) | [-0.018931; +0.013650] |

Az első 500 fixture közül 315 kimarad a mintaküszöb miatt (65/60/60/70/60 idényenként). Ezeket nem számítjuk találatnak vagy hibának az értékelt modellpár arányaiban. A részhalmazok pontbecslései kedvezőbbek, de mindkét NLL-intervallum átfedi a nullát; ez sem igazol aktiválást.

Az 1585 értékelt valódi meccsnél nincs core solver-fallback. A korrekciós korlát 68 meccsnél legalább az egyik lambdát korlátozza (4/22/30/7/5 idényenként). Minden alkalmazott arány a megengedett tartományban van. A baseline és core azonos meccseken, azonos címkékkel szerepel.

## Új regressziós ellenőrzések

`python -m unittest discover -s tests -v`: **31/31 sikeres, 8.303 s**, nincs skip. Ez a kísérleti modell ágának csomagja; nem a main 52 tesztjének újrafuttatása. Python compileall sikeres.

- Egy/két megfelelő hazai és vendég meccsnél a közvetlen becslő pontosan baseline-ra tér vissza, `insufficient_history_60_3_3` indokkal, aktív kísérleti jelzés nélkül. A backtest ezeket a meccseket mindkét modell számára kihagyja.
- Három-három megfelelő csapatmeccs és 60+ ligameccs mellett a ridge-es core illesztés konvergál, és a korrekció korlátozott.
- Ha egy új csapatnak egyetlen megfelelő helyszínspecifikus eredménye sincs, nincs baseline-becslés sem: explicit hiba/adathiány, nem kitalált csapaterősség.
- Másik idény eredményei nem kerülnek az új idény snapshotjába; üres előzménynél nincs becslés.
- Nagy gólszámú aznapi/jövőbeli sorok hozzáadása nem változtatja meg a snapshotot vagy a kevés adatos előrejelzést.
- A meglévő strict regressziók továbbra is ellenőrzik a rekordvisszavonást és az értékelési címkék/korabeli archívum szétválasztását.

## Időhelyesség és korlátok

Valódi adatoknál `historical_results_replay`: csak a célmeccs napja előtti eredmények. A végleges CSV-k korabeli elérhetőségét és későbbi javításait archívum nélkül nem lehet igazolni. A strict szabályok szintetikus, időbélyeges adatokon teszteltek; ez nem helyettesít valódi korabeli archívumot. Nincs új API-FOOTBALL-hívás, xG-/kezdő-/sérülésintegráció, ROI-mérés vagy eredményekre hangolás.

A mainen időközben éles PR #1 és #3 funkciói nem változnak. A PR #4 régi alapra épül: esetleges későbbi integráció előtt a jelenlegi mainnel újra össze kell dolgozni és a teljes alkalmazással ellenőrizni. A mostani csomag kizárólag tesztet, reprodukáló kutatási szkripteket és dokumentációt ad a kísérleti ághoz; nincs merge/deploy/modellaktiválás.

## Megismétlés

A források, nyers fájlhash-ek és korábbi letöltési időpontok: `TEAM_STRENGTH_DATA_SOURCES.json`. A bemeneti fájlok neve `E0_2021.csv`, `E0_2122.csv`, `E0_2223.csv`, `E0_2324.csv`, `E0_2425.csv`. Az adatokat a forrásmanifesthez kell ellenőrizni. A kutatási szkriptek nem töltenek le adatot vagy olvasnak API-kulcsot.

A repository gyökeréből:

```sh
PYTHONPATH=. python research/validate_team_strength.py --data-dir /path/to/csvs --output-dir /path/to/results
PYTHONPATH=. python research/audit_strength_cohorts.py --data-dir /path/to/csvs --result-dir /path/to/results --output /path/to/cohort_summary.json
python -m unittest discover -s tests -v
```

A mérés összesített és idényenkénti számai: `TEAM_STRENGTH_VALIDATION_20261024.json`. A futtató az összes meccsenkénti előrejelzést is kiírja a választott output könyvtárba. A dokumentált bootstrap nem kezeli teljesen az egymást követő napok/idényszakaszok összes függőségét; általános fölény vagy garantált fogadási eredmény nem következik belőle.
