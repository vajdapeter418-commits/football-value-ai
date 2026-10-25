# PR #14 – elkülönített PostgreSQL TESZT tároló: megvalósítási jelentés

## Eredmény és hatókör

A `technical_test_app.py` külön technikai tesztfelülete PostgreSQL-adaptert használ.
Az éles `streamlit_app.py`, a meglévő GitHub-archívum és a piaci modell/visszateszt implementációja változatlan. Az új adapter nem olvas és nem migrál helyi SQLite-adatot, nem kapcsolódik éles tárolóhoz és hibánál nem vált más tárolóra. A régi helyi TestStore csak offline regressziós segéd maradt; a UI-ban nincs hozzá kódút.

Kizárólagos fejlesztési ág: `feature/safe-technical-test-mode`.
A PR #14 draft, célága `feature/12-market-detective`. Nem történt merge, deployment, Streamlit-konfiguráció módosítása vagy futó alkalmazás újraindítása. A CI csak ideiglenes tesztadatbázis-folyamatot indít/leállít; ez nem a felhős alkalmazás.

## Megvalósítás

- `technical_test_postgres.py`: önálló szerveroldali adapter, explicit TESZT app/séma/verzió, DB-név és DB-szerepkör ellenőrzésével. Minden kapcsolat új tranzakció; sikeres kilépés commit, kivétel rollback. A driver részletes kivétele nem jut a felületre.
- `sql/technical_test_postgres.sql`: egyszeri, kizárólag külön TESZT adatbázison futtatandó adminmigráció. `identity` állapotsor és append-only `events` eseménytábla; `kind` különíti el a megfigyelés- és eredményláncot. Minden esemény fixture-kulcsot, megfigyelési/befejezési időt, DB-rögzítési időt, UUID-t, kérés-hash-t és teljes hash-lánc bejegyzést tartalmaz. A sorok TESZT prefixszel és meglévő szintetikus validációval védettek.
- Írás előtt `FOR UPDATE` sorzár, olvasás előtt ugyanazon állapotsor `FOR SHARE` zár biztosít konzisztens teljes láncot. Az írók nem számolnak egymással versengő láncvégeket; az olvasó nem lát félkész mentést.
- A DB `reserve_recording_time()` függvénye állítja elő a monoton rögzítési időt. Ezt az alkalmazásszerepkör nem írhatja át. SECURITY DEFINER függvények rögzített `pg_catalog` search_path-ot és teljesen minősített táblaneveket használnak; PUBLIC execute visszavont. Az INSERT trigger csak a saját tranzakcióban lefoglalt időt fogadja el.
- Az alkalmazásszerepkör eseményeket csak SELECT/INSERT művelettel kezel; UPDATE/DELETE/TRUNCATE jogosultságot nem kap. Az identity `id` oszlopának minimális UPDATE grantja kizárólag a PostgreSQL sorzár jogosultsági feltételét szolgálja. Az id CHECK/PRIMARY KEY miatt nem változtatható más értékre; a rögzítési idő oszlopaira nincs UPDATE grant.
- Egyedi UUID + kanonikus kérés-hash védi az ismétlést. Azonos kulcs/tartalom nem appendel újra, eltérő tartalom elutasított. Commit utáni elveszett válasz újrapróbálása ugyanazt a tartós kulcsot használja. Átmeneti kapcsolat-/zár-/tranzakciós hibánál legfeljebb három kísérlet van rövid várakozással. Validációs hiba nem ismétlődik automatikusan.
- A UI sessionönként külön mentési és eredményrögzítési kérésazonosítót tart meg; csak sikeres művelet után cseréli. Ez a böngészősession újrafuttatásaira ad stabil kulcsot; új böngészősessionben szándékosan új kérés keletkezik. Az adapter API-jában az explicit UUID ismétlése új processzből is idempotens.
- A meglévő OIDC, szigorúan boolean email_verified és email-engedélylista a tárolónyitás előtt fut. A kijelölt HTTPS host és explicit bekapcsolás mellett a Streamlit tényleges `main_script_path` értékének is a külön `technical_test_app.py` fájlra kell mutatnia. Más entrypoint importból sem nyithatja meg a felület tárolóját.
- A TLS `verify-full`, CA- és hosztnévellenőrzés, valamint a libpq tényleges TLS-állapotának ellenőrzése kötelező. A kapcsolat kizárólag `st.secrets['technical_test_postgres']` kötelező mezőiből készül. DSN, környezeti DB-jelszó, UI-mező vagy archívum-hitelesítő adat nem forrás. A libpq PG* környezeti beállítások jelenléte tilt, így service/hostaddr nem térítheti el a kapcsolatot. A password fájl útvonala `/dev/null`.
- Hiányzó Secrets, hibás TLS, nem megfelelő DB-azonosság vagy elérhetetlen DB esetén nincs olvasási/mentési felület. Műveleti hibánál a UI leállítja az adott futás további műveleteit, és nem állít sikeres mentést.

## Automatizált ellenőrzések

A `735f731c99f46f213fe7cdcf126f27e393a73e5f` commit CI-jában **158/158 teszt sikeres, nincs kihagyás**, valódi Streamlittel és TLS PostgreSQL-lel; futási idő 13,147 s. A compileall sikeres. A külön whitespace ellenőrzés három fájlvégi üres sort jelzett; ezek a jelentéssel együtt javításra kerültek. Ezért a hivatkozott futás teljes job-státusza még failure, jóllehet a tesztlépés sikeres:
https://github.com/vajdapeter418-commits/football-value-ai/actions/runs/40225953405 .
A végső fejcommit teljes CI-státuszát és futását az átadási válasz rögzíti.

| Ellenőrzés | Tartalom |
| --- | --- |
| 12 új adapter-egységteszt | Secrets hiány, TLS-paraméterek és titkosítatlan kapcsolat tiltása, PG service elutasítása, DB-idő, idempotencia, eltérő tartalmú kulcs, elveszett commitválasz, korlátozott retry, sérült lánc, fixture-ütközés, hibás eredmény és jövőbeli megfigyelés, titokmentes hiba, késői input cutoff-kizárása, éles entrypoint izoláció. |
| 3 valódi PostgreSQL-integrációs teszt | Nyolc konkurens azonos és nyolc külön kérés; új adapterből és ideiglenes DB-folyamat újraindítása után pontos visszaolvasás; kapcsolatleállás; hibás CA és sémaazonosság; szerepkör-jogosultságok. Az integrációs tesztet tovább bővítettük valódi INSERT utáni rollbackkel és direkt időbélyeg-hamisítás tiltásával. |
| 8 technikai Streamlit runtime teszt | Külön entrypoint működése, alternatív entrypoint tiltása, jogosulatlan látogató tárolónyitásának tiltása, hibás host/kapcsoló/kapcsolat, mentés, új UI-session visszaolvasás, eredmény és tényleges backtest, hibaüzenet titokmentessége. A UI-tesztek explicit tesztdublőrt használnak; a valódi DB külön integrációs teszt tárgya. |
| Meglévő regressziók | Modell-, archívum-, időrendi, cutoff-, eredményelkülönítési és felületi ellenőrzések. A meglévő visszatesztkód változatlan. |

Helyben a 12 adapter-egységteszt és 51 meglévő fókuszált regressziós teszt sikeres, valamint a compileall is. A teljes helyi csomag **nem sikeres**: 144 teszt, 26 Streamlit-hiány miatti importhiba és 14 kihagyás. A hálózati proxy nem tette lehetővé a helyi függőségtelepítést; ezt a valódi függőségekkel futó CI pótolja, nem rejtjük el skip mögött. A bekapcsolt CI PostgreSQL-integráció hiányzó előfeltételnél hibázik.

A tesztadatbázis és tanúsítvány teljesen eldobható, lokálisan generált. A loopback trust teszthitelesítés nem használható felhőben. Valódi API-kulcsot, jelszót vagy éles adatot a fejlesztés nem használ.

## A tényleges felhős kipróbálás előtt még szükséges

A teljes, lépésenkénti terv: [PR14_POSTGRES_INTEGRATION_PLAN.md](PR14_POSTGRES_INTEGRATION_PLAN.md).

Külön TESZT szolgáltatói projekt/DB, korlátozott szerepkör, admin által ellenőrzött migráció, hálózati elérés, szolgáltatói CA-csomag és kizárólag a tesztapp szerveroldali Secrets szekciója szükséges. Emellett igazolni kell a külön entrypoint deployment-hozzárendelését és a valódi OIDC/engedélylista működését. Ezeket jelen munka nem konfigurálta.

Külön későbbi engedéllyel kell elvégezni a tényleges felhős alkalmazás-újraindítási és újratelepítési próbát. Előtte/utána ugyanazon fixture-azonosítók, recorded_at értékek és hash-ek egyezése szükséges. A CI-ben az eldobható DB újraindítása és az új adapterpéldányos visszaolvasás igazolt; felhős redeploy-tűrést ez önmagában nem bizonyít.

Szolgáltatói backup/PITR és második TESZT DB-be visszaállítási próba, megőrzési szabályzat és elkülönített adminjogok is szükségesek. A teljes lánc minden műveletnél betöltődik és validálódik, ezért ez kis TESZT állományra készült. A hash-lánc nem aláírás; az adatbázis tulajdonosa elleni védelem és a régi backup visszaállításának felismerése külön infrastruktúra-bizonyítékot igényel.
