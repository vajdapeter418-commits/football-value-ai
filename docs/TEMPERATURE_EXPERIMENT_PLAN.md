# Kalibrációs kísérlet – rögzített protokoll

Rögzítve 2026-10-24, a kalibráció illesztése és eredményeinek megtekintése előtt. A korábbi hibadiagnózis már ismert; ez feltáró kísérlet, nem független megerősítés.

- Bemenet: az öt idény változatlan baseline előrejelzései, CSV SHA-256 `9a565df75e791b90ea6356cec1a15507de546554176dca402fb882748a03f486`. Egyetlen baseline-t vagy csapaterősség-paramétert sem módosítunk.
- Transzformáció: Q_T(h,a) = P(h,a)^(1/T) / sum(P^(1/T)), 0.5 <= T <= 2. A meglévő 0..100 gólos táblán normalizált közös eloszlás; a független margók miatt két egydimenziós log-sum-exp művelettel számolható. A top-1/top-5 sorrend és holtversenykezelés a baseline-é marad.
- Idényenként az eredeti development / validation / test dátumblokkok. T kizárólag development-előrejelzéseken, pontoseredmény-NLL minimumával illesztve. Determinisztikus, 40 iterációs aranymetszés a rögzített tartományban; T=1 és a két végpont is jelölt. Legalább 60 tanítópélda kell, különben identity.
- Validáció: a tanított jelöltet és identity-t egyaránt mérjük. Csak alacsonyabb validációs NLL és nem romló 1X2 Brier esetén választjuk a tanított jelöltet az adott idény végső blokkjára, egyébként identity. Mindkét változat eredményét közöljük, nem csak a kiválasztottét.
- A kiválasztás is tanult döntés: a végső blokkra fagyasztott artifact tartalmazza a validáció legkésőbbi dátumát. Nem használható e dátummal azonos vagy korábbi előrejelzésre. A development-illesztés a cutoff napját és a későbbi sorokat az illesztési hash előtt kizárja.
- Metrikák: pontoseredmény-NLL, 1X2 Brier, top-1/top-5 találat és becsült esély. A végső blokkokon a kiválasztott változat–baseline NLL-különbségéhez 2000, napcsoportos, seed=42 bootstrap újraminta. A top-1/top-5 találatoknak változatlannak kell maradniuk.
- Minden idényt közlünk. A most használt összes blokk már látott adat; nincs új érintetlen teszt, automatikus aktiválás, merge/deploy vagy odds-/API-kérés. Eredményektől függetlenül a baseline marad éles. További általánosításra új, előre félretett időszak kell.
