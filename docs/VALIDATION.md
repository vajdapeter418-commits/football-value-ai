# Ellenőrzési jegyzőkönyv – 2026-10-24

Python 3.12.14, Linux, standard könyvtári offline modelltesztek.

- `python -m unittest discover -s tests -v`: **24 sikeres teszt, 4.407 s**.
- `python -m compileall -q .`: sikeres, exit 0.
- `python -m streamlit run streamlit_app.py --server.headless true`: nem indult;
  `No module named streamlit`. Böngészős/mobilos és éles API-ellenőrzés nem készült.
- Közvetlen GitHub-klónozás: proxykapcsolati hiba. A forrásfájlok a GitHub
  connectoron keresztül, a rögzített main commitból kerültek a munkakönyvtárba.
- Football-Data letöltés/függőségtelepítés megszakadt; nincs valódi eredményfájl,
  ezért a valódi meccses párosított mérés **nem készült el**.
- Nincs valós extra adatkapcsolat vagy korabeli archívum. Az extra blokkok inaktívak;
  a fixture-β kizárólag tesztadat. Éles javulás és profit nem állítható.

A teljes tesztkimenet: [test-output.txt](test-output.txt).

## Repository és PR #1

Az ellenőrzött main továbbra is `82bc97984c3c471c0bece122f9ea8859c11ec0a3`.
PR #1: nyitott draft, merged=false, head
`04b2f4529edf9279f2673d40746dbe8cf2851fed`.
A top-1/top-5 és becsült lefedettség metrikái újra felhasználva, a háromelemű
`visszateszt` visszatérés és hívója egyeztetve. Az új szivárgási teszt a módosított
napot mindkét értékelésben megtartja, és a teljes előrejelzéseket hasonlítja össze
label/metrika nélkül. A baseline öt elemű szerződése változatlan.
A `detective_ui.py`, `odds_detective.py`, `requirements.txt` és a meglévő
dátumregressziós teszt változatlan. Sem éles API-, sem éles adatbázisírás nincs
a tesztekben. A jelenlegi FPL-panel változatlanul tájékoztató.

## Szintetikus integrációs mérés – nem éles teljesítménybizonyíték

Reprodukció a repository gyökeréből:

```sh
PYTHONPATH=tests:. python -c "from helpers import league; from correct_score_backtest import backtest; import json; print(json.dumps(backtest(league(100)), default=str))"
```

200 fixture-meccs / 100 nap, 140 értékelt, 60 kihagyott; futásidő 25.347 s.
Bemeneti rekordhash: `62d307c28805d3618f56371caae0498bd74834c5baadb6e46c1c525a5c7c601e`.

| Modell | Teszt n | Top-1 | Top-5 | Becsült top-1 | Becsült top-5 | NLL | Brier |
|---|---:|---:|---:|---:|---:|---:|---:|
| baseline | 40 | 15.0% | 62.5% | 17.8% | 59.8% | 2.384231 | 0.418200 |
| freshness | 40 | 5.0% | 62.5% | 17.7% | 59.9% | 2.363270 | 0.418510 |
| core | 40 | 5.0% | 77.5% | 17.2% | 60.5% | 2.231596 | 0.417872 |
| full | 40 | 5.0% | 77.5% | 17.2% | 60.5% | 2.231596 | 0.417872 |

A core top-1 ebben a fixture-ben romlik; ezt is közöljük. A teljes modell az
inaktív extrák miatt megegyezik a core-ral. A részletes Wilson- és bootstrap-
intervallumok, dátumhatárok, config/hash, lefedettség és fallbackek a
[synthetic-backtest-summary.json](synthetic-backtest-summary.json) fájlban vannak.
A 40 tesztmeccs és a mesterséges adat miatt a bizonyíték **elégtelen**;
aktiválás nem javasolt, baseline marad az alapértelmezés.

## Nyitott validációs korlátok

A 24 teszt nem jelenti a teljes specifikáció valamennyi elfogadási pontjának
igazolását. Valós szolgáltatói definíciók/adatjogok és extra archívumok ellenőrzése,
valódi szezonos mérés, Streamlit böngészős/mobilos ellenőrzés még szükséges.
Az extra időhelyes transzformációk és a regressziós interfész elkészültek, de a
stílus- és pontrúgásblokk teljes, valós adatos végponttól végpontig validációja
nem történt meg. A CLI eredmény-CSV replayt fogad, strict/extra archívumhoz
programozott integráció kell. Hiperparaméter-keresés nincs bekapcsolva.

Külön draft PR készül; automatikus merge/deploy és modellváltás nincs.


## PR #4 strict javítások

A javítás a `62ffdbc9c0c919674aad9cb355a1d8158e434c59` fejre épül.
A snapshot az elérhetőségi időbélyegek alapján választja ki a legújabb verziót,
és csak utána ellenőrzi a verifikációt, befejezést, játékidőt és meccsidőket.
A visszateszt külön `historical_matches` archívumot követel strict módban.
A végleges címkék kizárólag értékelésre szolgálnak. A strict extra-tanítás
címkéit minden új cutoffnál az akkori archívumból választja ki; visszavont
rekordból nem marad tanítópélda. A történeti feature-vektor megmarad a saját
előrejelzési cutoffján rögzített állapotában.

Regressziók: `python -m unittest discover -s tests -p test_strict_regressions.py -v`.
Mindkét teszt sikeres; az eredeti kódon hibát jeleznek (visszaéledő régi rekord,
illetve hiányzó archívumparaméter). A teljes csomag parancsa továbbra is
`python -m unittest discover -s tests -v`: 26/26 sikeres.
`python -m compileall -q .`: sikeres.

Valódi adatos újrafuttatás megkísérelve, de nem végrehajtható:
`curl --fail --show-error --max-time 20 https://www.football-data.co.uk/mmz4281/2526/E0.csv -o /workspace/E0-2526.csv`
exit 7: `Failed to connect to proxy port 8080`. Helyi valódi adat/korabeli
archívum nincs; nem közlünk kitalált mérési eredményt. A korábbi szintetikus
metrikák korábbi futás eredményei. A baseline és minden modellparaméter változatlan,
nincs teszteredményre hangolás, merge, deploy vagy modellaktiválás.
