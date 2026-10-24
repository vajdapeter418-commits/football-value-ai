# Pontos eredmények időrendi visszatesztje

Ellenőrzés: 2026-10-24. Integrációs alap: main `6e23fbb` (napi kereső és önálló API-diagnosztika).

## Számítás és időbeli határ

A meglévő `becsles`, `goltabla` és `pontos_eredmenyek` függvények változatlanok. Minden vizsgált D napra a tanítóminta kizárólag `match_date < D`; a teljes D nap kizárt, a meccsek aznapi sorrendje nem számít. A korábbi 60 ligameccses és legalább 3 megfelelő hazai/idegenbeli szerepléses küszöb változatlan. A kihagyott meccsek egyik értékelt mutató nevezőjébe sem kerülnek.

Top-1: a tényleges gólpár az első tippel azonos. Top-5: a gólpár az öt legvalószínűbb tipp között szerepel. A becsült arány az első cella valószínűsége, illetve az öt cella összege; az idényre ezek számtani átlaga jelenik meg. Egyenlő valószínűségnél a meglévő rendezés (hazai, majd vendég gólszám) dönt. A visszatérési érték `(1x2_sorok, kihagyott, pontos_sorok)`, minden értékelt mérkőzéshez egy-egy sorral. A pontos sorok dátumot, csapatokat, eredményt és az öt tipp valószínűségét is tartalmazzák az ellenőrizhetőséghez.

Ez végleges eredményadatokon végzett replay. Nem igazolja, hogy a szolgáltató ugyanazt a rekordverziót már az előrejelzés előtt közzétette; ehhez korabeli archívum kell. A felület ezt külön jelzi. A modell alapértelmezése és az 1X2 előrejelzése nem változik; kísérleti erősség-/xG-modell nem aktiválódik.

## Automatizált ellenőrzés

Python 3.12, telepített Streamlit mellett:

```
python -m unittest discover -s tests -v
python -m compileall -q .
```

52/52 teszt sikeres, 6.525 s, nincs kihagyott teszt; fordítás sikeres. A teljes main tesztcsomag is futott, benne a napi kereső és API-diagnosztika ellenőrzései.

A hibás régi szivárgási próba levágta az ellenőrizendő napot. Az új próba bent tartja a módosított aznapi és jövőbeli eredményeket, összeveti az aznapi tippeket/valószínűségeket, és minden becslőhívásnál ellenőrzi a tanítóminta dátumhatárát. A `< D` feltétel szándékos `<= D` elrontásakor a regressziós teszt megbukik (1 assertion failure, 0 runtime error). A jövőbeli sorok eltávolítása sem változtatja a korábbi pontos sorokat.

Külön tesztek: Poisson-tömeg, érvénytelen lambdák, üres/bemelegítő minta, ismert 1–1-es találat és determinisztikus holtverseny. Két valódi Streamlit AppTest ellenőrzi a mutatók megjelenését és az adathiányt nullával osztás nélkül. Az AppTest CSV-fixture-öt használ, az adatcache tesztenként ürül; nincs szolgáltatói hívás.

## Valódi eredményadatok

Football-Data, Premier League 2025/26: https://www.football-data.co.uk/mmz4281/2526/E0.csv . A korábban letöltött helyi állománnyal futtatva; nem állítunk új letöltést. SHA-256: `3e3a8352f9ada6789c508d6ca184424421fed56a30400904a4a327c583407e62`.

Időszak: 2025-08-15–2026-05-24; 380 bemeneti mérkőzés, 320 értékelt, 60 kihagyott.

| Mutató | Eredmény |
|---|---:|
| Top-1 találat | 37/320 = 11.5625% |
| Top-5 találat | 148/320 = 46.25% |
| Átlagos becsült top-1 esély | 12.3901% |
| Átlagos becsült top-5 esély | 49.6366% |
| Modell 1X2 Brier | 0.6330540171 |
| Ligaátlagos referencia Brier | 0.6583186355 |

A main korábbi kétértékű visszatesztjével az összes 1X2 sor és kihagyásszám pontosan megegyezik. Nincs eredményekre hangolás, fogadási hozam- vagy modelljavulás-állítás. Ez egy szezon leíró mérése; az átlagos becslés és találati arány eltérése önmagában nem teljes kalibrációs vizsgálat.

Az éles felület ellenőrzése az összeolvasztás után következik.
