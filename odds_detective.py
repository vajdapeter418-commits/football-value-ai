"""Evidence-preserving odds research. No betting or causal inference."""
import argparse
import hashlib
import json
import math
import os
import sqlite3
from datetime import datetime, timezone, timedelta
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

NA = "Nem elérhető"
KINDS = {"odds", "exchange", "news", "result"}
STATUSES = {"source_checked", "user_reported", "unverified", "rejected"}


def now():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def utc(value):
    if not isinstance(value, str):
        raise ValueError("Időbélyeg szükséges, időzónával.")
    d = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if d.tzinfo is None:
        raise ValueError("Az időbélyegből hiányzik az időzóna.")
    return d.astimezone(timezone.utc).isoformat(timespec="microseconds")


def url(value):
    if not isinstance(value, str) or urlparse(value).scheme not in {"https", "http"} or not urlparse(value).netloc:
        raise ValueError("Érvényes forrás-URL szükséges.")
    if urlparse(value).username or urlparse(value).query:
        raise ValueError("A forrás URL ne tartalmazzon hitelesítést vagy query paramétert.")
    return value


def number(value, minimum=0, strict=False):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("Véges numerikus érték szükséges.")
    if value < minimum or (strict and value == minimum):
        raise ValueError("Az érték a megengedett tartományon kívül esik.")
    return value


class Store:
    def __init__(self, path=None):
        path = path or os.environ.get("ODDS_DB_PATH", "data/odds_detective.sqlite3")
        if path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self.db = sqlite3.connect(path, timeout=20)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
        PRAGMA foreign_keys=ON;
        CREATE TABLE IF NOT EXISTS matches (
            id TEXT PRIMARY KEY, home TEXT NOT NULL, away TEXT NOT NULL,
            match_date TEXT NOT NULL, created_at TEXT NOT NULL,
            source TEXT NOT NULL, verification TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS evidence (
            id TEXT PRIMARY KEY, match_id TEXT NOT NULL REFERENCES matches(id),
            kind TEXT NOT NULL, source TEXT NOT NULL, source_time TEXT,
            collected_at TEXT NOT NULL, verification TEXT NOT NULL,
            payload TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS evidence_time ON evidence(match_id,kind,source_time);
        ''')

    def seed(self):
        self.db.execute("INSERT OR IGNORE INTO matches VALUES (?,?,?,?,?,?,?)", (
            "iberia-mjallby-2026-10-22", "FC Iberia 1999", "Mjällby AIF", "2026-10-22", now(),
            "Felhasználó által megadott teszteset", "user_reported"))
        self.db.commit()

    def matches(self):
        return [dict(r) for r in self.db.execute("SELECT * FROM matches ORDER BY match_date,id")]

    def add_match(self, home, away, date, source):
        if not home.strip() or not away.strip() or home.strip() == away.strip():
            raise ValueError("Két különböző csapat szükséges.")
        datetime.strptime(date, "%Y-%m-%d")
        mid = hashlib.sha256(f"{home}|{away}|{date}".encode()).hexdigest()[:24]
        self.db.execute("INSERT OR IGNORE INTO matches VALUES (?,?,?,?,?,?,?)",
                        (mid, home.strip(), away.strip(), date, now(), url(source), "user_reported"))
        self.db.commit()
        return mid

    def ingest(self, mid, records, trusted=False):
        if not isinstance(records, list) or len(records) > 10000:
            raise ValueError("Legfeljebb 10000 rekordot tartalmazó JSON-lista szükséges.")
        prepared = []
        for r in records:
            if not isinstance(r, dict) or r.get("kind") not in KINDS:
                raise ValueError("Ismeretlen rekordtípus.")
            kind, source = r["kind"], url(r.get("source"))
            stamp = utc(r["source_time"]) if r.get("source_time") else None
            status = r.get("verification", "unverified")
            if status not in STATUSES:
                raise ValueError("Ismeretlen ellenőrzési állapot.")
            if not trusted and status == "source_checked":
                status = "user_reported"
            if not isinstance(r.get("payload"), dict):
                raise ValueError("A payload JSON-objektum legyen.")
            p = dict(r["payload"])
            if kind == "odds":
                if not stamp or not isinstance(p.get("bookmaker"), str) or not p["bookmaker"].strip() or p.get("outcome") not in {"1", "X", "2"}:
                    raise ValueError("Odds: időbélyeg, iroda és 1/X/2 kimenetel szükséges.")
                number(p.get("odds"), 1, True)
            elif kind == "exchange":
                if not stamp or not p.get("market_id") or not p.get("currency"):
                    raise ValueError("Exchange: időbélyeg, piacazonosító és pénznem szükséges.")
                number(p.get("total_matched"))
                if not isinstance(p.get("runners", {}), dict):
                    raise ValueError("A kimenetelenkénti forgalom JSON-objektum legyen.")
                for outcome, amount in p.get("runners", {}).items():
                    if outcome not in {"1", "X", "2"}:
                        raise ValueError("Ismeretlen Exchange-kimenetel.")
                    number(amount)
            elif kind == "news":
                if not p.get("title") or p.get("category") not in {"injury", "suspension", "lineup", "rotation", "other"}:
                    raise ValueError("Hírcím és hírkategória szükséges.")
            elif kind == "result":
                if not stamp:
                    raise ValueError("Eredményhez közlési idő szükséges.")
                for key in ("home_goals", "away_goals"):
                    n = p.get(key)
                    if type(n) is not int or n < 0:
                        raise ValueError("Az eredmény nemnegatív egész gólszám legyen.")
                if p.get("period") != "FT_90":
                    raise ValueError("Csak rendes játékidős végeredmény (FT_90) rögzíthető.")
            canonical = json.dumps([mid, kind, source, stamp, status, p], sort_keys=True, ensure_ascii=False, allow_nan=False)
            eid = hashlib.sha256(canonical.encode()).hexdigest()
            prepared.append((eid, mid, kind, source, stamp, now(), status, json.dumps(p, ensure_ascii=False)))
        before = self.db.total_changes
        with self.db:
            self.db.executemany("INSERT OR IGNORE INTO evidence VALUES (?,?,?,?,?,?,?,?)", prepared)
        return self.db.total_changes - before

    def records(self, mid, cutoff=None):
        args = [mid]
        query = "SELECT * FROM evidence WHERE match_id=?"
        if cutoff:
            cutoff = utc(cutoff)
            query += " AND collected_at<=? AND source_time IS NOT NULL AND source_time<=?"
            args += [cutoff, cutoff]
        query += " ORDER BY source_time,collected_at,id"
        rows = []
        for r in self.db.execute(query, args):
            d = dict(r)
            d["payload"] = json.loads(d["payload"])
            rows.append(d)
        return rows

    def close(self):
        self.db.close()


def movements(records):
    groups = {}
    for r in records:
        if r["kind"] != "odds" or r["verification"] == "rejected" or r["payload"].get("odds") is None:
            continue
        p = r["payload"]
        # Never mix different providers or markets. In-play and pre-match stay separate.
        key = (r["source"], p["bookmaker"], p["outcome"], p.get("phase", "unknown"))
        groups.setdefault(key, []).append(r)
    changes = []
    for key, rows in groups.items():
        rows.sort(key=lambda r: (r["source_time"], r["collected_at"], r["id"]))
        # Conflicting prices with the same source timestamp cannot establish an order.
        counts = {}
        for r in rows:
            counts.setdefault(r["source_time"], set()).add(r["payload"]["odds"])
        rows = [r for r in rows if len(counts[r["source_time"]]) == 1]
        if not rows:
            continue
        opening = rows[0]["payload"]["odds"]
        for prev, cur in zip(rows, rows[1:]):
            old, new = prev["payload"]["odds"], cur["payload"]["odds"]
            if old == new:
                continue
            step, baseline = (new / old - 1) * 100, (new / opening - 1) * 100
            changes.append({"bookmaker": key[1], "outcome": key[2], "phase": key[3],
                "source_time": cur["source_time"], "previous_time": prev["source_time"],
                "old": old, "new": new, "step_pct": step, "baseline_pct": baseline,
                "review": abs(step) > 15 + 1e-9 or abs(baseline) > 15 + 1e-9,
                "source": cur["source"], "verification": cur["verification"]})
    return sorted(changes, key=lambda c: (c["source_time"], c["bookmaker"], c["outcome"]))


def first_observed(changes):
    result = []
    for outcome in ("1", "X", "2"):
        subset = [c for c in changes if c["outcome"] == outcome]
        if subset:
            first = min(c["source_time"] for c in subset)
            result.extend(c for c in subset if c["source_time"] == first)
    return result


def get_json(endpoint, params=None, headers=None):
    request = Request(endpoint + ("?" + urlencode(params) if params else ""),
                      headers={"User-Agent": "FootballValueAI/2.0", **(headers or {})})
    with urlopen(request, timeout=25) as response:
        return json.load(response)



def list_football_leagues(api_key):
    """Official catalogue, without an odds request or invented league keys."""
    if not api_key:
        raise ValueError("Hiányzik az ODDS_API_KEY.")
    data = get_json("https://api.the-odds-api.com/v4/sports/", {"apiKey": api_key})
    if not isinstance(data, list):
        raise ValueError("A bajnokságlista nem elérhető.")
    leagues = []
    for item in data:
        if not isinstance(item, dict):
            raise ValueError("Hibás bajnokságlista.")
        key = item.get("key", "")
        if (isinstance(key, str) and key.startswith("soccer_") and
                all(c.isalnum() or c == "_" for c in key) and item.get("active") is True
                and item.get("has_outrights") is False):
            if not isinstance(item.get("title"), str) or not item["title"].strip():
                raise ValueError("Hiányzó bajnokságnév.")
            leagues.append({"key": key, "title": item["title"]})
    return sorted(leagues, key=lambda item: item["title"].casefold())


def list_football_events(api_key, sport):
    """Prematch/live catalogue only. Empty is not proof a match does not exist."""
    if not api_key or not sport.startswith("soccer_") or not all(c.isalnum() or c == "_" for c in sport):
        raise ValueError("Érvényes kulcs és labdarúgó-bajnokság szükséges.")
    data = get_json(f"https://api.the-odds-api.com/v4/sports/{sport}/events", {"apiKey": api_key})
    if not isinstance(data, list):
        raise ValueError("A mérkőzéslista nem elérhető.")
    events = []
    for event in data:
        if not isinstance(event, dict) or event.get("sport_key") != sport:
            raise ValueError("Eltérő vagy hibás bajnokságadat.")
        if not isinstance(event.get("id"), str) or not event["id"].isalnum():
            raise ValueError("Hibás eseményazonosító.")
        if any(not isinstance(event.get(k), str) or not event[k].strip() for k in ("home_team", "away_team")):
            raise ValueError("Hiányzó csapatnév.")
        events.append({"id": event["id"], "sport_key": sport,
                       "home_team": event["home_team"], "away_team": event["away_team"],
                       "commence_time": utc(event["commence_time"])})
    return sorted(events, key=lambda event: (event["commence_time"], event["home_team"], event["id"]))


def events_on_date(events, match_date):
    datetime.strptime(match_date, "%Y-%m-%d")
    return [event for event in events if utc(event["commence_time"])[:10] == match_date]


def validate_event_binding(event, match, confirmed=False):
    if utc(event["commence_time"])[:10] != match["match_date"]:
        raise ValueError("A kiválasztott mérkőzés dátuma eltér a vizsgálatétól.")
    if (event["home_team"], event["away_team"]) != (match["home"], match["away"]) and not confirmed:
        raise ValueError("Az eltérő csapatnevek egyezését ellenőrizni kell.")


def odds_records(event, expected_home, expected_away, expected_date):
    if (event.get("home_team"), event.get("away_team")) != (expected_home, expected_away):
        raise ValueError("Az API csapatnevei eltérnek. Ellenőrizd az eseményazonosítót és a csapatneveket.")
    if utc(event["commence_time"])[:10] != expected_date:
        raise ValueError("Az API mérkőzésdátuma eltér a vizsgálattól.")
    records = []
    for book in event.get("bookmakers", []):
        for market in book.get("markets", []):
            if market.get("key") != "h2h":
                continue
            names = {expected_home: "1", "Draw": "X", expected_away: "2"}
            outcomes = market.get("outcomes", [])
            if len(outcomes) != 3 or {x.get("name") for x in outcomes} != set(names):
                continue
            for outcome in outcomes:
                records.append({"kind": "odds", "source": "https://api.the-odds-api.com/v4",
                    "source_time": market.get("last_update") or book.get("last_update"),
                    "verification": "source_checked", "payload": {
                        "bookmaker": book["key"], "outcome": names[outcome["name"]], "odds": outcome["price"],
                        "event_id": event["id"], "commence_time": event["commence_time"],
                        "phase": "prematch" if utc(event["commence_time"]) > now() else "inplay_or_post",
                        "time_basis": "provider_last_update"}})
    return records


def collect_odds(store, mid, api_key, sport, event_id, api_home, api_away):
    if not api_key or not sport.startswith("soccer_") or not all(c.isalnum() or c == "_" for c in sport) or not event_id.isalnum():
        raise ValueError("Odds API kulcs, soccer_ sportkulcs és eseményazonosító szükséges.")
    match = next(m for m in store.matches() if m["id"] == mid)
    endpoint = f"https://api.the-odds-api.com/v4/sports/{sport}/events/{event_id}/odds"
    event = get_json(endpoint, {"apiKey": api_key, "regions": "eu", "markets": "h2h", "oddsFormat": "decimal"})
    return store.ingest(mid, odds_records(event, api_home, api_away, match["match_date"]), trusted=True)


def betfair_records(catalogue, book, selection_map, currency, captured):
    if catalogue.get("description", {}).get("marketType") != "MATCH_ODDS" or str(catalogue.get("eventType", {}).get("id")) != "1":
        raise ValueError("Csak labdarúgó MATCH_ODDS piac használható.")
    if catalogue.get("marketId") != book.get("marketId"):
        raise ValueError("Eltérő Betfair piacazonosítók.")
    available = {str(r["selectionId"]) for r in catalogue.get("runners", [])}
    if set(selection_map) != {"1", "X", "2"} or len(set(selection_map.values())) != 3 or not set(selection_map.values()) <= available:
        raise ValueError("Három különböző, ellenőrzött Betfair selectionId szükséges.")
    if currency not in {"EUR", "GBP", "USD", "HUF", "AUD", "SEK", "DKK", "NOK", "CHF"}:
        raise ValueError("Ellenőrzött számlapénznem szükséges.")
    runners = {str(r["selectionId"]): r.get("totalMatched") for r in book.get("runners", [])}
    return [{"kind": "exchange", "source": "https://api.betfair.com/exchange/betting/rest/v1.0/listMarketBook/",
        "source_time": captured, "verification": "source_checked", "payload": {
            "market_id": book["marketId"], "market_name": catalogue.get("marketName"),
            "event_name": catalogue.get("event", {}).get("name"),
            "total_matched": book.get("totalMatched"), "runners": {k: runners.get(v) for k, v in selection_map.items()},
            "selection_map": selection_map, "currency": currency, "is_delayed": book.get("isMarketDataDelayed"),
            "time_basis": "api_observation", "market_status": book.get("status")}}]


def betfair_call(operation, params, app_key, session):
    req = Request("https://api.betfair.com/exchange/betting/rest/v1.0/" + operation + "/",
        data=json.dumps(params).encode(), headers={"X-Application": app_key, "X-Authentication": session,
        "Content-Type": "application/json", "User-Agent": "FootballValueAI/2.0"})
    with urlopen(req, timeout=25) as response:
        return json.load(response)


def collect_betfair(store, mid, app_key, session, market_id, selection_map, currency, confirmed=False):
    if not confirmed:
        raise ValueError("A piac és a kimenetelek egyezésének kézi ellenőrzése szükséges.")
    cats = betfair_call("listMarketCatalogue", {"filter": {"marketIds": [market_id]},
        "marketProjection": ["RUNNER_DESCRIPTION", "MARKET_DESCRIPTION", "EVENT", "EVENT_TYPE", "MARKET_START_TIME"], "maxResults": 1}, app_key, session)
    books = betfair_call("listMarketBook", {"marketIds": [market_id], "priceProjection": {"priceData": ["EX_TRADED"]}}, app_key, session)
    if not isinstance(cats, list) or len(cats) != 1 or not isinstance(books, list) or len(books) != 1:
        raise ValueError("A Betfair piac nem elérhető.")
    match = next(m for m in store.matches() if m["id"] == mid)
    if utc(cats[0]["marketStartTime"])[:10] != match["match_date"]:
        raise ValueError("A Betfair mérkőzésdátuma eltér.")
    return store.ingest(mid, betfair_records(cats[0], books[0], selection_map, currency, now()), trusted=True)


def search_news(home, away, match_date=None):
    from email.utils import parsedate_to_datetime
    query = f'"{home}" "{away}" (injury OR suspension OR lineup OR rotation OR sérülés OR kezdőcsapat)'
    if match_date:
        day = datetime.strptime(match_date, "%Y-%m-%d")
        query += f" after:{(day - timedelta(days=3)):%Y-%m-%d} before:{(day + timedelta(days=2)):%Y-%m-%d}"
    endpoint = "https://news.google.com/rss/search?" + urlencode({"q": query, "hl": "en", "gl": "GB", "ceid": "GB:en"})
    with urlopen(Request(endpoint, headers={"User-Agent": "FootballValueAI/2.0"}), timeout=25) as response:
        root = ET.fromstring(response.read(2_000_000))
    records = []
    for item in root.findall("./channel/item")[:40]:
        stamp = None
        if item.findtext("pubDate"):
            try:
                stamp = parsedate_to_datetime(item.findtext("pubDate")).isoformat()
            except (ValueError, TypeError):
                pass
        records.append({"kind": "news", "source": (item.findtext("link") or "").split("?")[0], "source_time": stamp,
            "verification": "unverified", "payload": {"title": item.findtext("title"), "category": "other",
            "publisher": item.findtext("source"), "search_query": query,
            "note": "RSS keresési találat; a cikk tartalma és az okság nincs ellenőrizve."}})
    return records


def main():
    parser = argparse.ArgumentParser(description="Egyszeri odds-pillanatkép mentése; külső cronból is hívható.")
    parser.add_argument("--match-id", required=True)
    parser.add_argument("--sport", required=True)
    parser.add_argument("--event-id", required=True)
    parser.add_argument("--home", required=True)
    parser.add_argument("--away", required=True)
    args = parser.parse_args()
    store = Store()
    store.seed()
    try:
        count = collect_odds(store, args.match_id, os.environ.get("ODDS_API_KEY"), args.sport, args.event_id, args.home, args.away)
        print(f"Új rekordok: {count}")
    except Exception:
        # HTTP errors can contain the API key in their URL. Never print exception details.
        print("Nem elérhető: a gyűjtés sikertelen. Ellenőrizd a hozzáférést, kvótát és az eseményazonosítót.")
        raise SystemExit(1)
    finally:
        store.close()


if __name__ == "__main__":
    main()
