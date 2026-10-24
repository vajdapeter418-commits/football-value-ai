# Felhőnapló: használat és egyszeri beállítás

## Mi készült el?

- Az Oddsmozgás-nyomozó napi EPL-listájában kiválasztott meccsnél a **Pontos tipp előkészítése**, majd ellenőrzés után a **Pontos tipp végleges mentése** gomb használható.
- Az új **Tippek naplója** oldalsávnézet a privát felhőből tölti vissza az előrejelzéseket. Egy új munkamenet/helyi fájlvesztés nem törli a GitHubon már sikeresen mentett naplót.
- A napló teljes JSON-ként letölthető és visszaállítható. A régi mentés nem törölhet újabb előrejelzést vagy eredményt, és az eltérő történet nem írhatja felül a meglévőt.
- A végeredmény külön, saját időbélyeges bejegyzésként rögzíthető. A rögzítőnek ellenőriznie kell a csapatokat, a tényleges kezdést és a rendes játékidős befejezést. Az eredeti előrejelzés változatlan marad. Javítás új eredményverzió; törölt/nem értékelhető meccs külön státusz, a kimaradások száma is látszik.
- Az összesítés kizárólag az elmentett tippekből számol top-1/top-5 találatot, pontoseredmény-NLL-t és 1X2 Briert. A kalibráció és csapaterősség továbbra sem aktív.

**Valódi felhőmentés még nem volt igazolva:** privát tároló/token/jelszó beállítása szükséges. A felület hiányzó beállításnál semmilyen mentést nem állít sikeresnek. Az offline és Streamlit-futtatókörnyezeti tesztek helyettesített GitHub-szolgáltatót használnak.

## Egyszeri, tulajdonosi lépések

1. A saját GitHub-fiókodban hozz létre egy **Private** tárolót, például `football-value-ai-archive` néven. Legyen benne README, hogy létrejöjjön az alapág. A meglévő Football Value AI forráskódtár nyilvános; azt nem használjuk a naplóhoz, és nem állítjuk át a láthatóságát.
2. Készíts fine-grained personal access tokent. Repository access: **Only select repositories**, kizárólag az új privát archívum. Repository permissions: **Contents — Read and write**, az alap Metadata-read mellett. Nem kell Actions-, Administration- vagy más tárolóhozzáférés. Válassz lejáratot; lejárat után a hozzáférést meg kell újítani.
3. A Streamlit alkalmazásban **Manage app → Settings → Secrets**. A meglévő API-kulcsokat tartsd meg. Az alábbi három új beállítást a gyökérszintre add hozzá, ne egy korábbi `[szekció]` alá. A helyőrzőket cseréld ki; a tokent és a naplójelszót ne küldd chatbe, és ne tedd a GitHub forráskódjába.

```toml
FORECAST_ARCHIVE_REPOSITORY = "vajdapeter418-commits/football-value-ai-archive"
FORECAST_ARCHIVE_TOKEN = "AZ_UJ_PRIVAT_TAROLOHOZ_TARTOZO_TOKEN"
FORECAST_JOURNAL_PASSWORD = "EGY_UJ_HOSSZU_EGYEDI_NAPLOJELSZO"
```

A naplójelszó külön saját jelszó, nem a GitHub-fiók jelszava és nem valamelyik API-kulcs. A GitHub-token csak a szerveren marad; a felületre ezt nem kell beírni. A tulajdonos a **Napló jelszava** maszkolt mezőben a külön naplójelszóval lép be. Ez egyszerű tulajdonosi hozzáférésvédelem, nem többfelhasználós fiókkezelés.

4. Beállításmentés és az alkalmazás frissítése után nyisd meg a **Tippek naplója** nézetet. Az első használatkor a **Felhőnapló létrehozása a privát tárolóban** gomb létrehozhatja a `forecast-archive` ágat és az üres `archive/forecast-journal.json` fájlt. Meglévő naplót nem nulláz le. Nyilvános tárolót a kód elutasít.
5. Válassz valóban közelgő EPL-meccset a napi listából, készítsd elő a tippet, ellenőrizd a CSV-neveket/kezdést, majd mentsd. Csak a GitHub-commit visszaigazolása után látszik siker. Új böngészőmunkamenetben a naplóoldalon ellenőrizd, hogy ugyanaz a bejegyzés visszatöltődött. E nélkül nincs igazolt éles felhőintegráció.

Hivatalos beállítási útmutatók: [GitHub tokenkezelés](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens), [Streamlit alkalmazásbeállítások és Secrets](https://docs.streamlit.io/deploy/streamlit-community-cloud/manage-your-app/app-settings).

## Adatfolyam és megőrzés

A gombnyomásos előkészítés egy nyilvános Football-Data CSV-letöltés. A lista API-azonosságát és a CSV-neveket a tulajdonos összekapcsolja; a rövid nevek néhány ismert aliasát előválasztjuk, ismeretlen egyezést nem találunk ki. A kezdés az API-listából kerül át. Az ellenőrző jelölés nem jelent független szolgáltatói hitelesítést. A tipp mentése továbbra is több mint öt perccel a kezdés előtt, 60/3/3 korábbi mintával történhet. Az aznapi és későbbi eredmények kizártak.

Minden felhőmódosítás előbb betölti és ellenőrzi a meglévő láncot. Az új állapot csak a meglévő történet folytatása lehet. A GitHub Contents API PUT a korábban olvasott fájl-SHA-t követeli; másik munkamenet közben történt módosításánál hiba és frissítési kérés következik, nem vak felülírás vagy automatikus újrapróbálás. Hálózati időtúllépés után a művelet állapota bizonytalan lehet: először vissza kell olvasni a felhőt, a duplikált meccsvédelem megőrzi az első tippet.

Nincs helyi-only mentési siker: az in-memory SQLite csak a tranzakció elkészítését szolgálja, az igazolt állapot a GitHub-fájl commitja. A fájl determinisztikusan gzip-tömörített JSON base64-burkolatban; legfeljebb 16 MiB kicsomagolt tartalom és 900000 bájtos burkolat. A korlát elérésekor nincs új mentés; külön archívumrotációt kell tervezni. Nincs beégetett token, automatikus háttérhívás vagy API-FOOTBALL-függőség. A jelszó megadása utáni naplóoldal-betöltés a felhőt olvassa; a tényleges írások gombnyomáshoz kötöttek.

Az eredmény legalább két órával a **tényleges** kezdés után és tulajdonosi befejezés-ellenőrzés mellett rögzíthető. Ha a tényleges kezdés a tipp rögzítése előtt volt, a rendszer nem számítja érvényes előrejelzésnek. Halasztásnál a valós kezdést kell megadni. Visszafelé mozduló eredményidő és előrejelzésidő tiltott. A forrás hivatkozott, kézzel ellenőrzött HTTPS-oldal; a rendszer most nem tölt le vagy hitelesít automatikus végeredményt.

A GitHub-verziózás és hash-lánc segíti az utólagos ellenőrzést, de nem külső időbélyeg-hitelesítés. A fiók/tároló/óra teljes hozzáférésével a történet átalakítható. Az importált fájl formailag ellenőrzött, eredete önmagában nem igazolt; a korábbi előrejelzési időpontot nem hitelesíti újra. A mérési periódus és teljes fixture-manifest előzetes rögzítése továbbra is szükséges, a sikertelen/kimaradt próbákkal együtt. A mostani UI nem indítja el automatikusan az első 200 meccses kutatást.

## Ellenőrzések

Az aktuális main + a teljes naplóváltozás tesztcsomagja: a kapcsolódó PR-ben rögzített futás. Külön lefedett: régi baseline, napi kereső és API-diagnosztika; előrejelzési időhatárok/immutabilitás; privát tároló kikényszerítése; fájl-SHA-ütközés és nincs vak retry; visszaállítás/történetrövidítés tiltása; eredményverziók és kimaradások; titkok nem kerülnek URL-be/kimenetbe; hiányzó beállítás/jelszó előtt nincs felhőhívás; valódi Streamlit AppTest a napi EPL-pickerből történő mentésre, friss munkamenetből visszatöltésre, eredményrögzítésre és hamis sikervisszajelzés tiltására.

Valódi tároló/token nem állt rendelkezésre a fejlesztői környezetben. A felhőkérés/ütközés tesztek mock HTTP-válaszokat használnak. Valódi privát GitHub roundtrip és Streamlit-restart utáni visszaolvasás még beállítás utáni elfogadási ellenőrzés.
