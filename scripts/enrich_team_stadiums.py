#!/usr/bin/env python3
"""Fill missing team stadium locations with the public Nominatim geocoder.

Runs sequentially and waits at least 1.1 seconds between requests, as required
by the public Nominatim service policy. Only stadium-like results are stored.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.database.schema import initialize_database

NOMINATIM = "https://nominatim.openstreetmap.org/search"
ATTRIBUTION = "© OpenStreetMap contributors"
CITY_HINTS = {
    "1 FC Slovacko": "Uherské Hradiště", "FC Banik Ostrava": "Ostrava-Vítkovice",
    "FC FASTAV Zlin": "Zlín", "FC Slovan Liberec": "Liberec",
    "FC Zbrojovka Brno": "Brno", "SK Artis Brno": "Brno",
    "FK Mlada Boleslav": "Mladá Boleslav", "FK Teplice": "Teplice",
    "SK Sigma Olomouc": "Olomouc",
}


def lookup(query: str, user_agent: str) -> dict | None:
    params = urlencode({"q": query, "format": "jsonv2", "addressdetails": 1, "limit": 5})
    request = Request(f"{NOMINATIM}?{params}", headers={"User-Agent": user_agent, "Accept": "application/json"})
    with urlopen(request, timeout=25) as response:
        results = json.load(response)
    for item in results:
        kind = str(item.get("type", "")).casefold()
        category = str(item.get("category", item.get("class", ""))).casefold()
        name = str(item.get("name", ""))
        query_terms = _terms(query.split(",", 1)[0])
        name_terms = _terms(name)
        same_named_place = bool((query_terms - {"mestsky", "fotbalovy", "stadion", "stadium", "arena", "football", "ground", "czechia", "czech"}) & name_terms)
        if same_named_place and (kind in {"stadium", "sports_centre", "sports_ground", "pitch"} or (category == "leisure" and any(x in name.casefold() for x in ("stadion", "stadium", "arena", "ground")))):
            return item
    return None


def _terms(value: str) -> set[str]:
    value = unicodedata.normalize("NFKD", value.casefold())
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return {part for part in "".join(ch if ch.isalnum() else " " for ch in value).split() if len(part) >= 4}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=ROOT / "database/football.db")
    parser.add_argument("--user-agent", default="FootballAnalysisEngine/1.0 (https://github.com/CowleyCZE/FootballAnalysisEngine)",
                        help="Identifying application/contact for the geocoder")
    args = parser.parse_args()
    initialize_database(str(args.db))
    with sqlite3.connect(args.db, timeout=30) as conn:
        teams = conn.execute("""SELECT t.id,t.name,s.stadium_name FROM teams t
            LEFT JOIN team_stadiums s ON s.team_id=t.id
            WHERE (s.latitude IS NULL OR s.longitude IS NULL) AND s.stadium_name IS NOT NULL
              AND trim(s.stadium_name)<>'' ORDER BY t.name""").fetchall()
        success = failed = 0
        last_request = 0.0
        for index, (team_id, team_name, stadium_name) in enumerate(teams, 1):
            if not stadium_name:
                continue
            city = CITY_HINTS.get(str(team_name), "")
            query = f"{stadium_name}, {city}, Czechia" if city else f"{stadium_name}, Czechia"
            delay = 1.1 - (time.monotonic() - last_request)
            if last_request and delay > 0:
                time.sleep(delay)
            try:
                item = lookup(query, args.user_agent)
                last_request = time.monotonic()
            except Exception as exc:
                print(f"{index}/{len(teams)} {team_name}: geocoding error: {exc}", flush=True)
                failed += 1
                continue
            if not item:
                print(f"{index}/{len(teams)} {team_name}: no stadium match", flush=True)
                failed += 1
                continue
            address = item.get("address") or {}
            conn.execute("""INSERT INTO team_stadiums(team_id,stadium_name,city,country,latitude,longitude,
                source,source_url,attribution,geocoded_at,updated_at) VALUES(?,?,?,?,?,?, 'Nominatim',?,?,?,CURRENT_TIMESTAMP)
                ON CONFLICT(team_id) DO UPDATE SET stadium_name=COALESCE(team_stadiums.stadium_name,excluded.stadium_name),
                city=excluded.city,country=excluded.country,latitude=excluded.latitude,longitude=excluded.longitude,
                source=excluded.source,source_url=excluded.source_url,attribution=excluded.attribution,
                geocoded_at=excluded.geocoded_at,updated_at=CURRENT_TIMESTAMP""",
                (team_id, item.get("name") or stadium_name, address.get("city") or address.get("town") or address.get("village") or address.get("municipality"),
                 address.get("country"), float(item["lat"]), float(item["lon"]),
                 f"https://www.openstreetmap.org/{item.get('osm_type','node')}/{item.get('osm_id','')}",
                 ATTRIBUTION, datetime.now(timezone.utc).isoformat()))
            conn.commit()
            success += 1
            print(f"{index}/{len(teams)} {team_name}: {item.get('name')} ({item['lat']},{item['lon']})", flush=True)
    print(f"Hotovo: {success} geokódováno, {failed} bez ověřené polohy.")
    print(ATTRIBUTION)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
