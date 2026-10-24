# Streamlit kapcsolati próba – validáció

2026. október 24. Python 3.12.14, Streamlit 1.66.1.

- `python -m unittest discover -s tests -v`: **41/41 sikeres, 6.612 s**, nincs kihagyott teszt.
- `python -m compileall -q .`: sikeres.
- `git diff --check`: sikeres.
- Valódi `streamlit.testing.v1.AppTest`: első megjelenítés 0 provider-hívás, első kattintás 1, ismételt kattintás után továbbra is 1. Nincs Streamlit runtime-kivétel. A fixture-kulcs nincs a megjelenített szövegben vagy táblában.
- Helyettesített providerrel teszteltük; valódi API-FOOTBALL-hálózati hívás nem történt. A felhasználó csak a Secrets bejegyzés nevét erősítette meg (`API_FOOTBALL_KEY`), a kulcs értékét nem kaptuk meg és nem kértük el.
- A szerveren a kulcs közvetlenül `st.secrets`-ből olvasható. A CLI továbbra is környezeti változóból működik. A kulcs értékét nem tesszük session_state-be, renderelt szövegbe, URL-be vagy cache-kulcsba; cache-azonosítóként csak SHA-256 digest szerepel.
- Az alkalmazás eredeti két oldala megmarad. Az új oldalsávos nézet nem indítja el a másik két oldal adatletöltését. A modellfüggvényeket nem módosítottuk.

## Éles ellenőrzés később

Ellenőrzött célelvárás: a telepített kód új nézete az **API-kapcsolat ellenőrzése** menüpont. A felhasználó kiválasztja az idényt és megnyomja az ellenőrző gombot. A kijelzés tartalmazza a kapcsolat eredményét, az UTC mérési időt és a forrás által közölt négy lefedettségi jelzőt. Ha nincs ismert jelző, azt külön jelzi. Nem mutat kulcsrészletet, nyers API-választ vagy kivételszöveget.

A tényleges https://football-value-ai-gxnnkwdctuup5s6xgzzs9q.streamlit.app/ oldalon nem igazoltunk telepítést, és a felhasználó saját kulcsával nem futott próba. A draft PR még nem éles. Korábbi instrukció szerint nincs automatikus merge/deploy. A PR #5 a PR #4 ágára épül, tehát nem szabad úgy mainre olvasztani, mintha csak ez az új menüpont lenne benne. Élesítés előtt a telepített ágat és a teljes összeolvasztási különbséget is ellenőrizni kell.

A kvótakorlát az adott SQLite-fájlt használó sessionökre közös. A fájl elvesztése/resetje után a helyi számláló is újraindul. A szolgáltató saját kvótáját nem tudjuk ezzel teljesen garantálni.

Hivatalos referenciák:

- https://docs.streamlit.io/develop/api-reference/connections/st.secrets
- https://www.api-football.com/news/post/how-to-get-started-with-api-football-the-complete-beginners-guide
