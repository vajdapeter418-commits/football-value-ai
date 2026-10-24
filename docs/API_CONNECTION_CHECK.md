# Önálló API-FOOTBALL kapcsolati próba a főágon

2026. október 24. Alap: `main`, `82bc97984c3c471c0bece122f9ea8859c11ec0a3`.

Ez a változat a kapcsolati próbát önállóan adja a főághoz. Nem függ a PR #4-től vagy #5-től. Nem tartalmazza a kísérleti csapaterősségi modellt, az új pontoseredmény-visszatesztet vagy azok moduljait.

## Felület és működés

- Új oldalsávos elem: **API-kapcsolat ellenőrzése**.
- A meglévő `API_FOOTBALL_KEY` Streamlit Secrets bejegyzést olvassa; környezeti változós fallback is van. Nem kell és nem lehet kulcsot beírni a felületre. Nem jelenít meg kulcsrészletet, nyers API-választ vagy kivételszöveget.
- A Premier League ligaazonosítója rögzítetten 39; az idény kezdőéve választható. Csak a gomb indít kérést.
- Egy sikeres kérés az adott liga/idény elérhetőségét ellenőrzi. Négy boolean/ismeretlen jelzőt mutat: sérülések/hiányzók; kezdők; meccsstatisztikák; játékosstatisztikák. A statisztikai lefedettség nem garantálja az xG meglétét. Az adatlétezés nem igazolja a modell teljesítményét.
- Egyórás közös cache: az ismételt kattintás a mentett ellenőrzést mutatja. A kulcs nincs a cache-kulcsban; kizárólag a SHA-256 digestje választja szét a különböző konfigurációkat.
- SQLite-alapú közös korlát: UTC-naponként öt új próbálkozás, minimum 60 másodperc eltéréssel. Hibás kérés is számít. A helyi fájl elvesztése/törlése ezt a számlálót is elveszíti, ezért ez nem teljes szolgáltatóoldali kvótavédelem.

## Mentés és a modul határai

A független `prematch_archive.py` standard könyvtári modul biztosítja a nyers lefedettségi válasz helyi tárolását. A fájl az előző draftban már tesztelt FPL CLI-segédet is tartalmazza, de azt az új Streamlit-oldal nem hívja és nem indítja automatikusan. Nem szükségesek hozzá a kísérleti modell moduljai.

Alapértelmezett adatbázis: `data/prematch_archive.sqlite3`; felülírható a `PREMATCH_ARCHIVE_DB` környezeti változóval. Más adatbázist és korábbi vizsgálatot nem módosít. A `data/` és a helyi `.streamlit/secrets.toml` gitignore-olt. A mentések publikálási ideje ismeretlen, a rögzítési idő aktuális; a később rögzített adat nem olvasható korábbi cutoffhoz. Ezekből nem készül automatikusan modell-feature vagy λ-korrekció.

Kulcs nélküli lokális ellenőrzés nem indít API-hívást. A szerveroldali kulccsal a CLI is futtatható:

```sh
python prematch_archive.py coverage --league 39 --season 2026
```

A CLI környezeti változót használ, a Streamlit-oldal közvetlenül olvassa a Secrets értékét. Kulcs nem kerülhet parancssori argumentumba vagy GitHubra. Nincs új függőség, automatikus ütemezés vagy háttérgyűjtés. Community Cloudon a helyi SQLite nem garantáltan tartós.

## Saját validáció

Python 3.12.14, Streamlit 1.66.1:

- `python -m unittest discover -s tests -v`: **21/21 sikeres, 1.518 s**, nincs skip. A kísérleti modell tesztjei itt nincsenek jelen; ezért a tesztszám nem azonos a PR #5 korábbi 41 tesztjével.
- `python -m compileall -q .`: sikeres.
- `git diff --check`: sikeres.
- A főág `streamlit_app.py` fájljának mind a 13 meglévő függvénye AST szerint változatlan. A meglévő modell nincs újraszámolva vagy kicserélve; kizárólag az oldalsáv és az új nézet elágazása változik.
- `detective_ui.py`, `odds_detective.py`, `README.md`, `requirements.txt`: bájtra változatlan.
- `team_strength.py`, `asof_features.py`, `correct_score_backtest.py`, `poisson_model.py`: nem kerülnek ebbe az ágba.
- Valódi Streamlit AppTest, helyettesített HTTP/API-val: a teljes főoldal fixture-CSV-vel betölt; az API-nézetre váltás nem indít más adatletöltést; első kattintás egy lefedettségi kérés; ismétléskor továbbra is egy; nincs runtime-kivétel. Külön teszt ellenőrzi, hogy a fixture-kulcs nem kerül a megjelenített tartalomba.
- További tesztek: hiányzó kulcs, Secrets elsőbbsége, hibás provider-válasz/kivétel elrejtése, közös napi korlát, cutoff, atomi mentés és integritás.

A saját Streamlit-kulccsal nem futott élő kérés; a kulcs értékét nem kértük el. A beállítás nevét a felhasználó erősítette meg. Telefonos böngészős és tényleges éles ellenőrzés még nincs. Az alkalmazás címe: https://football-value-ai-gxnnkwdctuup5s6xgzzs9q.streamlit.app/ .

## Élesítési döntés és későbbi próba

Ez külön draft PR, közvetlenül a `main` ágra céloz. Elégséges a kapcsolati tesztfelülethez, a PR #4/#5 összeolvasztása nem előfeltétele. A draft létrehozása nem telepítés. A korábbi instrukció alapján nincs automatikus merge/deploy. Élesítés előtt ellenőrizni kell, hogy a Streamlit alkalmazás ténylegesen melyik repositoryt, ágat és belépési pontot futtatja. A forráskódot csak ezen ellenőrzés és külön élesítési jóváhagyás után kell az aktív ágra helyezni.

Telepítés után: **API-kapcsolat ellenőrzése → idény → Kapcsolat és lefedettség ellenőrzése**. A megjelenített eredmény és időpont alapján értékelhető a valódi hozzáférés. A kulcs értékét vagy a Secrets képernyőjét ekkor sem kell megosztani.

Referenciák:

- https://docs.streamlit.io/develop/api-reference/connections/st.secrets
- https://www.api-football.com/news/post/how-to-get-started-with-api-football-the-complete-beginners-guide

# Secrets beolvasási diagnosztika (2. verzió)

A korábbi általános „nem érhető el” üzenet helyett fix, titokérték nélküli állapot jelenik meg: olvashatatlan Secrets (hiányzó fájl vagy TOML-hiba), üres beállítás, hiányzó legfelső szintű bejegyzés, szakasz alá került bejegyzés, illetve üres/nem szöveges érték. A beágyazott kulcs keresése legfeljebb nyolc szintű; ilyen kulcsot a program nem használ automatikusan. Az elsőbbség továbbra is legfelső szintű Secrets, majd környezeti változó. Más kulcsnevek, szakasznevek, értékek és kivételszövegek nem jelennek meg. Ez nem API-hitelesítés és nem fogyaszt szolgáltatói kvótát.

# Konkrét mérkőzéspróba

Az API-kapcsolat menü alján külön gomb indítja a 2024-08-16-i Manchester United–Fulham mérkőzés ellenőrzését. Egy szigorúan rögzített `/fixtures?league=39&season=2024&date=2024-08-16` hívás után ellenőrzi a liga, idény, UTC-nap, hazai/vendég csapatazonosítók és FT státusz egyezését. Csak az így kapott pozitív fixture ID használható a három további végponthoz: `/fixtures/statistics`, `/fixtures/lineups`, `/injuries`.

A próba legfeljebb 4 GET, nincs átirányítás vagy újrapróbálkozás. A meglévő legfeljebb napi 5 kapcsolati hívás mellett külön naponta egy, legfeljebb 4 hívásos közös kerete van. SQLite tranzakció foglalja le az UTC-napot hálózati kérés előtt; sikertelen és megszakadt próba is fogyasztja a keretet. Az azonos kulccsal történő ismételt kattintás a biztonságos összesítést olvassa a SQLite-ból, nem újabb szolgáltatói kérés. Helyi adatbázisvesztés visszaállítja e korlátot is.

A felület csak fix szöveget, darabszámokat és ellenőrzött, nemnegatív, véges xG-számokat mutat. A hiányzó vagy nem numerikus xG nem nulla; a valódi nulla megmarad. Csapat- és játékosazonosítók ellenőrzése megakadályozza a rossz párosítás elfogadását. A hiányzók üres válasza nem jelent hiányzómentességet. A sikeres fixture-azonosítás nem jelenti minden részlekérés sikerét; azok külön állapotot kapnak.

Az archívum `api_football_sample` névtérbe ment, aktuális fetched/stored/available időponttal, ismeretlen publikálási idővel, `model_eligible=False` jelöléssel. Ezek mai megfigyelések egy lezárt meccsről, nem bizonyítékok a kezdés előtt elérhető információra. A modell és a visszateszt nem olvassa őket.

Dokumentáció: https://www.api-football.com/documentation_v3

