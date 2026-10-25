# PR #14 – PostgreSQL TESZT integrációs és felhős elfogadási terv

A fejlesztés kizárólag a `feature/safe-technical-test-mode` ágon történik.
Ez a dokumentum jövőbeli üzemeltetési lépéseket ír le; nem engedélyez és nem hajt végre deploymentet, alkalmazás-újraindítást vagy konfigurációváltoztatást.

## Szükséges külső beállítások

1. Külön szolgáltatói TESZT projekt és adatbázis, az éles adatbázistól és GitHub-archívumtól függetlenül. Ne használjon éles adatot, API-kulcsot, szerepkört vagy jelszót. Az adatbázis célpontjának elkülönítését a szolgáltatói adminnak is igazolnia kell; egy alkalmazásazonosság-jelölő önmagában nem bizonyít infrastruktúra-elkülönítést.
2. Külön migrációs tulajdonos és külön `fva_test_app` alkalmazásszerepkör. Az alkalmazásszerepkör nem tulajdonos, nem superuser, nincs CREATEDB/CREATEROLE/BYPASSRLS joga, éles szerepkör-tagsága vagy örökölt éles hozzáférése. PUBLIC CONNECT/TEMP/CREATE és a public séma CREATE jogosultságait a tesztprojekt szabályai szerint vissza kell vonni. Az SQL-vázlat nem hoz létre felhasználót vagy jelszót és nem fut automatikusan az app indulásakor.
3. Az admin kizárólag a külön tesztadatbázison futtassa a `sql/technical_test_postgres.sql` migrációt. Ez egyszeri, tranzakciós migráció; meglévő séma esetén hibázik, nem javítja/írja felül automatikusan. A futtatás után ellenőrizni kell a tulajdonosokat és a grantokat. Eltérő szerepnév esetén a grantokat ellenőrzötten kell átírni.
4. A külön tesztalkalmazás **szerveroldali Secrets** konfigurációjában a `technical_test_postgres` szekció szükséges. Kötelező mezők: `host`, `port`, `dbname`, `user`, `password`, `sslrootcert`. A `sslrootcert` a szolgáltatói CA-csomag szerveren olvasható abszolút útvonala. A CA-csomag nyilvános tanúsítvány, nem jelszó. Az adapter PG* környezeti beállítás jelenlétében letilt; nem fogad el kliensoldali DSN-t, URL-t, környezeti jelszót vagy UI-ban megadott kapcsolatot. A tényleges Secrets fájlt nem szabad commitolni. TLS: rögzített `verify-full`, CA- és hosztnévellenőrzéssel; nem kapcsolható ki konfigurációból.
5. A felhőből kizárólag a TESZT DB címére szükséges hálózati hozzáférés. Nincs szükség GitHub-archívum hitelesítő adataira vagy futballadat-API kulcsára. Külső connection pooler csak session/tranzakciós viselkedésének külön ellenőrzése után használható.
6. Külön tesztapp-hozzárendelés: repo, fejlesztési ág és `technical_test_app.py` belépési pont. A `streamlit_app.py` változatlan, nem importál technikai UI-t. A technikai UI a Streamlit tényleges `main_script_path` értékét is ellenőrzi.
7. Meglévő kapuk megtartandók: kijelölt HTTPS teszthost, `FVA_TECH_TEST_ENABLED=1`, platform OIDC, boolean `email_verified=True`, és a külön `FVA_TECH_TEST_ALLOWED_EMAILS` engedélylista. Kizárólag a DB kapcsolat olvassa a dedikált Secrets szekciót; a meglévő nem titkos engedélyezési beállítások helye nem változik. A konfigurálást és app-újraindítást ez a munka nem végzi el.
8. Szolgáltatói backup/PITR, megőrzési idő, hozzáférési naplózás és külön TESZT visszaállítási cél szükséges. A hash-lánc nem digitális aláírás és nem helyettesíti a backupot vagy az infrastruktúra-jogosultságokat.

## Automatizált lokális/CI integráció

A `tests/test_technical_postgres_integration.py` saját ideiglenes, loopbackre kötött PostgreSQL klasztert és egynapos, tesztre generált TLS-tanúsítványt készít. Nem csatlakozik felhős adatbázishoz, nem olvas alkalmazás-Secrets konfigurációt. A helyi tesztszerepkör loopback trust hitelesítést használ; a kódban szereplő jelszószöveg szintetikus, nem használható valós szolgáltatáshoz. Ez a hitelesítési mód felhőben tilos.

Feltételek: nem root Linux-felhasználó, Python-függőségek, PostgreSQL binárisok és openssl. Futtatás:

```bash
export FVA_RUN_LOCAL_POSTGRES_TESTS=1
export FVA_TEST_POSTGRES_BIN="$(pg_config --bindir)"
python -m unittest discover -s tests -v
```

A CI ezt bekapcsolja; hiányzó előfeltétel esetén a bekapcsolt teszt hibázik. Kikapcsolt helyi környezetben a három integrációs teszt explicit skip, nem minősül sikeres PostgreSQL-igazolásnak.

Vizsgálatok: nyolc párhuzamos azonos kulcsú append csak egy sort készít; nyolc külön kulcsú konkurens append mind megmarad; eltérő tartalmú kulcsismétlés elutasított; UPDATE/DELETE tiltott; megszakított tranzakció visszagördül; hibás CA vagy sémaazonosság tilt; új adapterből és az ideiglenes PostgreSQL tesztfolyamat leállítása/indítása után a teljes állapot változatlan. Ez kizárólag eldobható tesztadatbázis-folyamat; futó alkalmazás újraindítása nem történik.

## Későbbi felhős elfogadás – külön engedélyezett művelet

| Lépés | Elvárt bizonyíték |
| --- | --- |
| Jogosulatlan/hiányzó OIDC és engedélylistán kívüli felhasználó | Nincs tárolónyitás, adatolvasás vagy mentési űrlap; login működését valódi platformon kell igazolni. |
| Két független böngészősession | Közösen olvasott szintetikus fixture, időbélyeg, entry_hash és sorösszeg egyezik. |
| Konkurens mentés és hálózati válasz elvesztése | Azonos UUID és tartalom ismétlése egyetlen esemény; eltérő tartalom hibázik. DB commit utáni elveszett válasz esetére is ellenőrizni kell. |
| TLS/kapcsolat/jogosultság hibája | Sem olvasás, sem mentés nem érhető el; nincs SQLite, éles DB vagy GitHub-archívum fallback, és nincs titok a UI-ban. |
| Időrendi visszateszt | DB recorded_at az alap; utólag bevitt, korábbi observed_at nem válik cutoff előtt ismert adattá; eredmény nem kerül jellemzőbe. |
| Új alkalmazáspéldány | Korábban rögzített fixture-kulcsok, sorok, recorded_at és hash-lánc pontosan azonosak. |
| **Külön engedélyezett alkalmazás-újraindítás** | Indítás előtti/utáni rekordlista és hash összeg egyezik, új mentés hozzáfűzhető. |
| **Külön engedélyezett újratelepítés/konténercsere** | Ugyanaz a külső TESZT DB, azonos rekordazonosítók/idők/hash-ek; nincs automatikus üres DB-inicializálás. |
| Backup/PITR visszaállítás második TESZT DB-be | Dokumentált helyreállítási időpont, láncellenőrzés, elvárt sorösszeg és hozzáférés-elkülönítés. |

A próbák naplójában commit SHA, időpont, tesztprojekt nem titkos azonosítója, sorösszeg és hash szerepelhet; DSN, jelszó, API-kulcs, OIDC token és éles adat nem. A redeploy utáni tartósság csak a tényleges felhős elfogadás után állítható. Jelen munka ezt nem hajtja végre.
