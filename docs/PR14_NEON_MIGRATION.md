# PR #14 – előkészített Neon TESZT migráció

Kizárólag a külön Neon tesztprojekt `neondb` adatbázisán futtatandó,
`neondb_owner` szerepkörrel. A projekt/host elkülönítését a Neon konzolban
ellenőrizd; az adatbázis neve önmagában nem igazolja ezt.
Ez a fejlesztés nem futtat felhős migrációt és nem telepít alkalmazást.

A meglévő `fva_technical_test` séma elfogadott, ha a futtató tulajdona,
üres és nincs idegen grantja. Nemcsak táblák, hanem minden namespace-függő
objektum ellenőrzött. Más tulajdonos, meglévő objektum vagy hibás jogosultság
kivételt okoz; a teljes migráció tranzakciós. Sikeres futás után az újrafuttatás
szándékosan hibázik. Nincs DROP, CREATE OR REPLACE vagy adatfelülírás.

Előfeltétel: külön, már létrehozott `fva_test_app` LOGIN NOINHERIT szerepkör,
superuser/CREATEDB/CREATEROLE/REPLICATION/BYPASSRLS nélkül; nincs tagsága
egyik irányban sem, tulajdona vagy meglévő alkalmazásobjektum-joga.
CONNECT kell, CREATE és TEMP nem lehet az adatbázison, PUBLIC-on keresztül sem.
A public sémán CREATE nem lehet. Az ellenőrzés hibánál nem javítja automatikusan
a projekt globális jogosultságait. A szükséges jogosultságkorrekció külön
adminfeladat; ne vond vissza más alkalmazások jogait ellenőrzés nélkül.
A migrációs tulajdonos egyedi default ACL-je sem adhat idegen grantot.

A futtatás idején más admin ne hozzon létre objektumot a sémában.
A tranzakciós advisory lock az ugyanezt a migrációt futtató munkameneteket
sorba állítja; tetszőleges admin DDL-t nem zár ki.

Előellenőrzés a Neon SQL Editorban, a kijelölt tesztprojekten:

```sql
SELECT current_database(), session_user, current_user;
SELECT nspname, pg_get_userbyid(nspowner) AS owner
FROM pg_namespace WHERE nspname='fva_technical_test';
SELECT count(*) AS namespace_dependencies
FROM pg_depend WHERE refclassid='pg_namespace'::regclass
AND refobjid=to_regnamespace('fva_technical_test');
```

Elvárt: neondb / neondb_owner / neondb_owner, séma tulajdonosa neondb_owner,
függőségek száma 0. Ezután a **teljes** `sql/technical_test_postgres.sql`
fájl futtatandó, BEGIN-től COMMIT-ig, egyetlen műveletben.
Hiba után SQL Editorban `ROLLBACK;`, majd az ok kivizsgálása szükséges.

Parancssori megfelelő (a kapcsolat hostja, CA-ja és hitelesítése a külön TESZT
projekthez legyen konfigurálva, TLS verify-full használatával):

```bash
psql -X --set=ON_ERROR_STOP=1 --dbname=neondb --username=neondb_owner --file=sql/technical_test_postgres.sql
psql -X --set=ON_ERROR_STOP=1 --dbname=neondb --username=neondb_owner --file=sql/technical_test_postgres_verify.sql
```

A második fájl kizárólag olvasó ellenőrzésekből áll. Friss migrációnál egy
identity sor (football-value-ai-market-test / TESZT-postgres-v1), nulla esemény,
két tábla és egy identity sequence várható; a tulajdonos neondb_owner.
A szerepkör minden veszélyes attribútuma false, LOGIN true, INHERIT false.
A lekérdezések nevében jelzett true/false értékeknek egyezniük kell.
Az alkalmazás csak a reserve_recording_time függvényt futtathatja közvetlenül.

Lokális/CI validáció: a kibővített TLS PostgreSQL teszt friss és meglévő üres
sémát, megőrzött táblát/adatot, függvényt és típust, hibás tulajdonost,
schema/default/column grantokat, PUBLIC-on keresztüli jogokat, szerepkör-
attribútumokat, mindkét irányú tagságot és újrafuttatás elutasítását vizsgálja.
