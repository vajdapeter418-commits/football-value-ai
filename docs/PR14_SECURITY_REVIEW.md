# PR #14 – kiegészítő biztonsági és működési ellenőrzés

Vizsgálati alap: `7fa21c099a68e6848cabd734679fc188c2b29a02`.
Kizárólagos fejlesztési ág: `feature/safe-technical-test-mode`.
A PR draft marad, célága `feature/12-market-detective`.

## Bizonyított hibák és javítások

1. **Hiányzó látogatói jogosultságellenőrzés.** A korábbi UI csak a bekapcsolást
   és a hostot ellenőrizte, majd minden látogatónak megnyitotta a tárolót és az
   olvasási/mentési/eredményrögzítési felületet. Ez kódszinten bizonyított,
   bekapcsolás esetén kihasználható hozzáférési hiba. Nem állítjuk, hogy a futó
   nyilvános alkalmazásban ténylegesen bekapcsolták vagy kihasználták.
   Javítás: tárolónyitás előtt Streamlit OIDC `is_logged_in`, szigorúan boolean
   `email_verified=True` és külön `FVA_TECH_TEST_ALLOWED_EMAILS` engedélylista.
   Hiányzó claim/konfiguráció tilt. Query, Host, session_state és saját checkbox
   nem szolgáltat identitást. A bejelentkezés az `st.login()` platform API-jával
   kezdeményezhető; konfigurációs hiba nem tesz hozzáférhetővé adatot.
   Az engedély minden újrafuttatáskor, a tároló megnyitása előtt ellenőrzött.
   Engedélyezett tesztelők közös olvasási és írási jogot kapnak; nincs néző szerep.

2. **Fájlcsere a vizsgálat és SQLite-megnyitás között.** Az eredeti kódot külön,
   ideiglenes szintetikus fájlokon futtatva a `sqlite3.connect` előtti symlinkcsere
   után a mentés ténylegesen módosította a külső célfájlt. Az eredeti formátumú
   szintetikus másolat megfelelt a tartalomellenőrzésnek. Ez determinisztikusan
   reprodukált TOCTOU hiba; valódi adatfájl nem szerepelt a próbában.
   Javítás: minden könyvtárelem `O_NOFOLLOW` és könyvtári fájlleíró útján nyílik;
   a fájl típusát, tulajdonosát, linkszámát és írhatóságát `fstat` ellenőrzi.
   A SQLite kizárólag `:memory:` adatbázist nyit, a biztonságosan beolvasott
   másolatot `deserialize` tölti be. Idegen trigger/index/view is elutasított.
   A lemezadatbázist SQLite soha nem nyitja meg, nem hoz létre journal fájlt.
   Íráskor ugyanabba a rögzített könyvtárba új, kizárólagosan létrehozott fájl
   készül, majd flush/fsync, atomi replace és könyvtár-fsync következik.
   A cél symlinkje nem követhető; művelet közben észlelt inode-csere tilt.

3. **Nem összehangolt első inicializálás és útvonalbejárás.** A korábbi exists /
   mkdir és exists / create / DDL műveletek nem voltak közösen zárolva. Másik
   példány üres, még inicializálatlan adatbázist is láthatott. Ezt két szál
   vezérelt időzítésével az eredeti kódban ValueError hibával reprodukáltuk. A journal fájl
   ellenőrzés közben eltűnhetett. Javítás: szülőkönyvtári `flock` az első
   létrehozásra, rögzített gyökérkönyvtári `flock` minden teljes olvasási/írási
   ciklusra. Nem használunk átneveződő DB-inode-ot zárolási objektumként.
   Nyolc önálló folyamat egyidejű első megnyitása és mentése mind megmarad.
   A korábbi `BEGIN IMMEDIATE` már védett a szokásos elveszett frissítéstől;
   itt az inicializálási és fájlkezelési réseket kellett javítani.

4. **A fő belépési pontot környezeti kapcsoló eltérítette.** Korábban az éles
   belépési fájl `FVA_TECH_TEST_ENABLED=1` esetén az eredeti navigáció helyett
   technikai felületre váltott (idegen hoston hibaoldalra). A kapcsoló kikerült
   a `streamlit_app.py` fájlból. A technikai UI egyetlen külön belépési pontja
   `technical_test_app.py`. Az eredeti belépési pont kódja az alapágéval azonos;
   csak a fájlvégi üres sorok korábbi eltávolítása marad. Nincs importkapcsolat
   a technikai és az eredeti alkalmazás belépési pontjai között.

## Visszateszt és időrendiség

A `market_backtest` és `market_research` meglévő implementációját nem módosítottuk.
Ugyanazon fixture két külön mentett, eltérő időpontú odds-pillanatképéből egyetlen
értékelt sor keletkezik. A teszt kézzel kiszámolt normalizált implicit
valószínűség-különbséggel ellenőrzi a mozgás százalékpontértékét és a kiválasztást.
Utólag bevitt, korábbi megfigyelési idejű szélsőséges odds sem a sort, sem a
mozgásszabály összesítését nem változtatja meg. A szerverrögzítés cutoffja,
a pontos határ és +1 mikrosec kizárása, valamint az eredménycímke elkülönítése
külön regressziós ellenőrzések. Az azonos fixture kezdési ideje nem írható át
észrevétlenül, így nem tolható el utólag a cutoff. Ez technikai, szintetikus
visszajátszás, nem érintetlen out-of-sample teljesítményigazolás.

## Külön tartós TESZT tároló terve

A helyi SQLite a Community Cloud redeploy/konténercsere túlélésére **nem megoldás**.
Javaslat: külön szolgáltatói projektben külön menedzselt PostgreSQL-adatbázis,
kizárólag szintetikus TESZT adatokhoz. Nem az éles DB, nem az éles archívum,
nem a meglévő GitHub-tárolókapcsolat vagy annak hitelesítő adatai.

1. Külön tesztprojekt, külön DB és kizárólag erre jogosult alkalmazásszerepkör;
   nincs elérési vagy öröklött jogosultság az éles projekt felé. TLS kötelező.
   Új kapcsolatbeállítás csak a tesztdeployment saját Secrets tárolójába kerülhet,
   egy későbbi külön üzemeltetési lépésben. A jelen munka ilyet nem hoz létre.
2. Append-only megfigyelés- és eredménytáblák TESZT jelöléssel, fixture-kulccsal,
   megfigyelési idővel, DB által beállított rögzítési idővel és hash-lánccal.
   A kliens rögzítési időt nem adhat meg és nem frissíthet. A szerveróra és UTC
   az időrend alapja. Külön explicit séma-/alkalmazásazonosság ellenőrzése.
3. Tranzakciónként zárolt állapotverzió vagy sorzár védi az append/hash-láncot;
   egyedi idempotenciakulcs akadályozza meg a hálózati retry duplikációját.
   Konfliktusra korlátozott újrapróbálás, hibánál tiltás; nincs éles/helyi fallback.
   A szerveroldali adapter a jelenlegi validációt és cutoff-szabályt megtartja.
4. Minden olvasás/írás a hitelesített tesztfelületen át történik; nincs publikus
   adatbázis-API, böngészőbe adott DB-kulcs vagy anonim olvasási szabály.
5. Külön tesztmentések, szolgáltatói backup/PITR, dokumentált megőrzés és
   visszaállítási próba egy második, szintén elkülönített tesztadatbázisban.
6. Elfogadási próba: mentés két független sessionből, konkurens append és retry,
   hálózati hiba, jogosulatlan olvasás/írás, új alkalmazáspéldányból visszaolvasás,
   majd külön engedélyezett redeploy és ugyanazon azonosító/hash/idő visszamérése.
   Csak ennek dokumentált sikere után tekinthető redeploy-tűrőnek.

## Nyitott kockázatok és aktiválási feltételek

- A futó Streamlit app repo/ág/belépési pont hozzárendelése és hozzáférési
  konfigurációja nincs adminisztratívan igazolva. Távoli adatírási próbát nem
  végeztünk. A hostellenőrzés önmagában nem deployment-hitelesítés.
- OIDC és a külön engedélylista jelenleg nincs általunk konfigurálva. Ezek nélkül
  az új felület zárva marad. Privát Community Cloud app, minimális meghívotti kör
  és MFA javasolt további platformvédelemként. A meglévő credentialök érintetlenek.
- POSIX `flock`, `O_NOFOLLOW`, SQLite serialize/deserialize szükséges; célkörnyezet
  Linux/Python 3.12. Hálózati fájlrendszerre a helyi zárolás nem minősített.
- Azonos OS-felhasználóként vagy rendszergazdaként futó támadó nem kizárható
  alkalmazásszintű fájlellenőrzéssel. Egy érvényes, hash-lánccal együtt lecserélt
  régi másolat új példányból nem különböztethető meg hiteles külső horgony nélkül.
  A hash-lánc nem titkosított aláírás. Külön runtime-felhasználó és dedikált kötet
  szükséges, ha helyi tárolót később használnak.
- A teljes DB memóriába töltése nagy tesztállományra nem skálázódik. A dedikált
  PostgreSQL terv kiváltja ezt. Folyamatleállás közvetlenül az atomi csere előtt
  pending fájlt hagyhat, amelyre a tároló biztonságosan letilt; ellenőrzött kézi
  helyreállítás kell. Sérült tároló automatikus javítása/migrációja nincs.
- Felhős tartósság, backup-visszaállítás és valós OIDC-platformintegráció továbbra
  is külön elfogadási vizsgálat. Ezek nem helyettesíthetők mockolt AppTesttel.

## Validáció és műveleti korlátok

Helyben 56 fókuszált tárolási/biztonsági/piaci regressziós teszt sikeres.
A teljes `python -m unittest discover -s tests -v` újrafuttatása helyben megtörtént,
de a Streamlit hiánya miatt nem sikeres (128 teszt, 26 importhiba, 10 skip).
Ez nem teljes sikeres regresszió; a PR GitHub Actions környezetében a valódi
függőségekkel a teljes csomagnak is le kell futnia. A javítás kódcommitján (`e3d835bf5c0fafdaea8562dbfc8a17815e9c6fc2`) a GitHub
Actions valódi Streamlittel **142/142 tesztet sikeresen, kihagyás nélkül** futtatott
(11,805 s). A compileall is sikeres. A whitespace ellenőrzés három fájlvégi
üres sort jelzett; ezeket a következő commit eltávolítja. Az ellenőrzött futás:
https://github.com/vajdapeter418-commits/football-value-ai/actions/runs/40223558434 .
A végleges fejcommit teljes CI-eredményét az átadási jelentés rögzíti.
A compileall és diff whitespace ellenőrzés külön fut.

A vizsgálat nem módosít main ágat, telepített alkalmazást, meglévő naplókat,
éles adatokat vagy hitelesítő adatokat. Nincs merge, telepítési parancs vagy
alkalmazás-újraindítás. A meglévő workflow csak tesztel, deploy lépést nem tartalmaz.
