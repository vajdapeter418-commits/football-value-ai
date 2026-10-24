# A jelenlegi baseline hibadiagnosztikája – 2026-10-24

**Elsődleges további kutatási irány: a pontoseredmény-esélyek kalibrációja.** Nincs bizonyított új javítás vagy aktiválás. Az átlagos gólszám kis eltérése nem indokol automatikus, általános gólszorzót; a döntetleneket és külön a 0–0/1–1 eredményeket sem indokolt egyformán korrigálni.

## Adatok és módszer

A korábban elmentett 2020/21–2024/25 Premier League előrejelzéseket olvastuk vissza. 1900 bemeneti meccsből 1585 értékelt; az eredeti tesztblokkok 368 meccsét külön is közöljük. Ezek mind már látott adatok, így az elemzés utólagos diagnosztika, nem új független teszt vagy kalibrátortanítás.

Előrejelzés-CSV SHA-256: `9a565df75e791b90ea6356cec1a15507de546554176dca402fb882748a03f486`. A baseline `becsles`, `goltabla`, `pontos_eredmenyek` függvényeinek AST-je egyezik az élesített PR #1 utáni alkalmazás függvényeivel. A fő mutatókat az eredeti JSON-forecastokból is külön újraszámoltuk, 1e-12 tolerancián belül egyeznek. A diagnosztika nem hívja meg a becslőt és nem illeszt paramétert; a már korábbi napokból számolt lambdákból értékeli a Poisson-esélyeket. Nem használ oddsot vagy új szolgáltatói adatot.

## Gólszámok, döntetlenek és alacsony eredmények

| Mutató | 1585 meccs: becsült | 1585 meccs: tényleges | Eredeti 368 tesztmeccs: becsült | Eredeti 368 tesztmeccs: tényleges |
|---|---:|---:|---:|---:|
| Hazai gól | 1.557 | 1.566 | 1.566 | 1.679 |
| Vendég gól | 1.331 | 1.346 | 1.338 | 1.391 |
| Összes gól | 2.887 | 2.912 | 2.904 | 3.071 |
| Döntetlen | 23.25% | 22.40% | 22.90% | 19.29% |
| 0–0 | 6.32% | 5.55% | 6.21% | 3.26% |
| 1–1 | 10.59% | 10.22% | 10.41% | 9.51% |
| 1–0 | 8.90% | 9.40% | 8.80% | 10.05% |
| 0–1 | 7.83% | 6.44% | 7.73% | 5.16% |
| 2–2 | 4.98% | 5.49% | 4.92% | 5.71% |
| Első pontos tipp | 11.80% | 9.78% | 11.82% | 10.60% |
| Legvalószínűbb 1X2 kimenetel | 52.14% | 52.05% | 53.17% | 58.15% |

A teljes mintán a modell 2.887 gólt vár meccsenként, a tény 2.912. A tény mínusz becslés különbség 0.024 gól, napcsoportos 95%-os intervalluma [-0.058; +0.112]; nincs egyértelmű állandó góleltolás. Az eredeti tesztblokkokon nagyobb a különbség (0.167), de ez a már látott végső szezonrészek utólagos megfigyelése, nem általános gólszorzó igazolása.

A teljes mintán a döntetlenek tényleges aránya 0.85 százalékponttal marad el a becsléstől; intervallum [-3.02; +1.25] százalékpont. A 0–0 különbsége -0.77, az 1–1-é -0.36 százalékpont; mindkét teljesmintás intervallum átfedi a nullát. Az eredeti tesztblokkokon a 0–0 ritkább (12/368 = 3.26%, várt 6.21%), de az 1–1 eltérése és a döntetlenek teljes eltérése bizonytalan. Nem állítjuk, hogy minden döntetlen-esélyt csökkenteni kell.

A pontos top-1 tippek átlagesélye 11.80%, találati aránya 9.78% (155/1585). A tény mínusz becslés -2.02 százalékpont, leíró bootstrap intervalluma [-3.46; -0.47]. Az eredeti tesztblokkokon viszont az eltérés -1.22 százalékpont és az intervallum [-4.37; +2.04], ezért az összesített jelzés nem tekinthető független megerősítésnek. A legvalószínűbb 1X2 kimenetel összesített becslése 52.14%, tényleges aránya 52.05%; ez önmagában nem jelenti az összes egyedi esély jó kalibrációját.

## Magasabb esélyű tippek

A csoportokat kizárólag a meccs előtt rögzített becsült esély határozza meg, nem a végeredmény. Határok: top-1 esetén 0/10/15/20/100%, legvalószínűbb 1X2 esetén 0/40/50/60/70/80/100%. Balról zárt, jobbról nyitott intervallumok; az utolsó 100%-ot is befogadja. Nem keresünk utólag optimális fogadási küszöböt.

| Első pontos tipp becsült esélye | n | Átlagos becslés | Tényleges találat |
|---|---:|---:|---:|
| 0–10% | 359 | 9.19% | 37/359 = 10.31% |
| 10–15% | 1100 | 12.10% | 101/1100 = 9.18% |
| 15–20% | 122 | 16.51% | 17/122 = 13.93% |
| 20–100% | 4 | 20.28% | 0/4 = 0.00% |

A 10–15%-os csoportban 1100 meccsen 12.10% átlagos becslés mellé 9.18% találat tartozik. A 15–20%-os csoportban a találati arány magasabb (13.93%), de csak 122 meccs van, és a bizonytalanság nagy. A 10% alatti csoport jobban teljesít, mint a 10–15%-os: a vizsgált mintán nincs tökéletesen monoton kapcsolat a becsült esély és a tényleges találat között. A 20% feletti négy meccsből nem következtethetünk általános pontosságra.

| Legvalószínűbb 1X2 kimenetel becsült esélye | n | Átlagos becslés | Tényleges találat |
|---|---:|---:|---:|
| 0–40% | 193 | 38.19% | 89/193 = 46.11% |
| 40–50% | 608 | 44.63% | 260/608 = 42.76% |
| 50–60% | 394 | 54.63% | 210/394 = 53.30% |
| 60–70% | 262 | 64.32% | 170/262 = 64.89% |
| 70–80% | 102 | 74.45% | 75/102 = 73.53% |
| 80–100% | 26 | 83.33% | 21/26 = 80.77% |

Az 1X2 csoportokban összességében növekszik a találati arány a becsült eséllyel, de ez nem garantál egyedi találatot vagy fogadási előnyt. A 80% feletti csoport csak 26 meccs, ezért különösen bizonytalan.

## Idényenkénti ellenőrzés

| Idény | n | Hazai gól: tény−becslés | Vendég gól: tény−becslés | Döntetlen: tény−becslés (százalékpont) | Top-1: tény−becslés (százalékpont) |
|---|---:|---:|---:|---:|---:|
| 2020/21 | 315 | -0.031 | -0.157 | -2.25 | -1.65 |
| 2021/22 | 320 | +0.012 | +0.081 | -0.71 | -3.65 |
| 2022/23 | 320 | -0.066 | +0.095 | -1.73 | -3.94 |
| 2023/24 | 310 | +0.126 | +0.060 | +0.32 | +0.32 |
| 2024/25 | 320 | +0.008 | -0.005 | +0.13 | -1.10 |

A 0–0-t a 2020/21-es idényben alulbecsüli, a többi négyben túlbecsüli a modell. A góleltérések előjele is változik. Ezek az eltérések óvatosságot indokolnak egyetlen állandó korrekcióval szemben.

## Bizonytalanság és ellenőrzések

2000 páros, idény+dátum szerint csoportos bootstrap újraminta, seed=42. A reziduum a tény mínusz előzetes becslés; a góleltérések gól/meccs, az eseménykülönbségek valószínűségi egységben értendők. Az intervallumok pontonkénti, leíró intervallumok, több összehasonlításra nincsenek korrigálva; nem tekintjük a nullát kizáró egyedi cellákat bizonyított, általános modellhibának.

Kevés meccs (<50), kevés napcsoport (<20), illetve teljesen azonos találati kimenetelek esetén a csoportos reziduum-bootstrapot nem közöljük. Ilyenkor a JSON `limited_sample=true` jelzést és a megfigyelt találati arány Wilson-intervallumát tartalmazza. A Wilson-intervallum nem kezeli a csoportfüggőséget; a nullatalálatos kis minták bizonytalanságát jelzi, nem bizonyít kalibrációs hibát. A nagyobb minták napcsoportos bootstrapja sem kezeli teljesen a szomszédos napok közötti függőséget.

A kísérleti ág teljes tesztcsomagja az új kézi Poisson-, csoporthatár-, bootstrap- és sérült forecast-ellenőrzésekkel: **35/35 sikeres, 5.525 s**, nincs skip. Compileall sikeres. Ez nem a main 52 tesztjének újrafuttatása, és nem éles felületi változás.

## Következő ellenőrizhető kísérlet

1. A baseline rögzítve marad; külön kalibrációs kísérlet indulhat kizárólag fejlesztési adaton, időrendi belső felosztással. A korábban látott végső tesztblokkokat nem szabad újra érintetlen tesztként használni.
2. Első egyszerű jelöltként a teljes pontoseredmény-eloszlás egyparaméteres hőmérséklet-kalibrációja vizsgálható: P_T(h,a)=P(h,a)^(1/T)/ΣP^(1/T), T>0. A paraméter csak korábban megismert adatokon illeszthető; minden célmeccsre fagyasztott változat kell. Ez kutatási javaslat, a T értékét most nem választottuk ki.
3. Ez a transzformáció önmagában nem változtatja meg a top-1/top-5 sorrendet, tehát nem ígér több találatot: a közölt esélyek és a teljes eloszlás megbízhatóságát célozza. Az 1X2 esélyeket ugyanabból a normalizált közös eloszlásból kell újra összegezni; a baseline továbbra is választható és változatlan.
4. Előre kijelölt, eddig nem használt későbbi adatokon kell összevetni a pontoseredmény-NLL-t, az 1X2 Briert és a kalibrációt, változatlan jogosultsággal. A most látott 2020/21–2025/26-os eredmények nem nevezhetők új érintetlen tesztnek. Sem fejlesztési nyereség, sem az itt látott részcsoport nem elég az élesítéshez.

A diagnosztika nem készíti el vagy aktiválja ezt a kalibrátort, nem indít időzített gyűjtést, nem módosít modellt vagy felületet. A valódi adatok végleges eredmény-CSV-kből származó replayek; az akkori szolgáltatói elérhetőség és későbbi rekordjavítás archívum nélkül nem bizonyított.

## Megismétlés

```sh
python research/diagnose_baseline.py /path/to/predictions.csv --output /path/to/diagnostics.json
python -m unittest discover -s tests -v
```

Gépi eredmények, idénybontás és intervallumok: `BASELINE_DIAGNOSTICS_20261024.json`. Az input az előző, változatlan beállítású többidényes validáció `predictions.csv` fájlja; a források és hash-ek a `TEAM_STRENGTH_DATA_SOURCES.json` fájlban találhatók.
