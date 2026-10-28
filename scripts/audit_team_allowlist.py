#!/usr/bin/env python3
"""Read-only comparison of database teams with approved CSV sources."""
from __future__ import annotations

import argparse
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.statistics.csv_data_sync import _pick, _read_csv  # noqa: E402
from app.statistics.history_autofill import resolve_team_key  # noqa: E402


def approved_csvs(data_dir: Path) -> list[Path]:
    paths = sorted(data_dir.rglob("*.csv"))
    for path in (ROOT / "molcup_vysledek.csv", ROOT / "zapasy_xg.csv"):
        if path.is_file():
            paths.append(path)
    return paths


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=ROOT / "database/football.db")
    parser.add_argument("--data-dir", type=Path, default=ROOT / "database/data_csv")
    args = parser.parse_args()

    names_by_key: dict[str, set[str]] = defaultdict(set)
    league_keys: set[str] = set()
    paths = approved_csvs(args.data_dir)
    for path in paths:
        try:
            rows, _ = _read_csv(path)
        except (OSError, UnicodeError, ValueError) as exc:
            print(f"CHYBA CSV {path}: {exc}")
            return 2
        is_league_feed = any(tag in path.name.casefold() for tag in
                             ("chance_liga", "czech_league", "tabulka_liga", "s&f_liga"))
        for row in rows:
            home = _pick(row, "home_team", "home", "domaci")
            away = _pick(row, "away_team", "away", "hoste")
            if home and away and resolve_team_key(home) == resolve_team_key(away):
                # Ignore malformed self-fixtures rather than treating their names
                # as evidence that those clubs belong in the database.
                continue
            row_names = [home, away, _pick(row, "squad", "team", "tym", "tým")]
            for name in row_names:
                key = resolve_team_key(name)
                if not key:
                    continue
                names_by_key[key].add(name.strip())
                if is_league_feed:
                    league_keys.add(key)

    with sqlite3.connect(args.db) as conn:
        db_teams = [(int(row[0]), str(row[1])) for row in conn.execute("SELECT id,name FROM teams ORDER BY name")]
        historical_keys = {resolve_team_key(str(row[0])) for row in conn.execute("""
            SELECT DISTINCT t.name FROM teams t JOIN matches m
              ON t.id=m.home_team_id OR t.id=m.away_team_id
            WHERE lower(coalesce(m.competition,'')) LIKE '%chance liga%'
        """)}
        historical_keys.discard("")

    db_by_key: dict[str, list[tuple[int, str]]] = defaultdict(list)
    for ident, name in db_teams:
        db_by_key[resolve_team_key(name)].append((ident, name))
    duplicate_ids = {key: rows for key, rows in db_by_key.items() if key and len(rows) > 1}
    csv_keys = set(names_by_key)
    allowed_keys = csv_keys | league_keys | historical_keys
    outside = [(ident, name) for ident, name in db_teams if resolve_team_key(name) not in allowed_keys]
    missing = sorted((key, sorted(values)) for key, values in names_by_key.items() if key not in db_by_key)

    print(f"Týmů v DB: {len(db_teams)} | CSV zdrojů: {len(paths)} | týmů v CSV: {len(csv_keys)} | aktuální liga: {len(league_keys)}")
    print(f"Historické identity Chance Ligy zachované podle utkání: {len(historical_keys)}")
    print(f"Týmy mimo povolené zdroje: {len(outside)} | CSV týmy chybějící v DB: {len(missing)} | duplicitní identity: {len(duplicate_ids)}")
    for ident, name in outside:
        print(f"  MIMO DB {ident}: {name}")
    for key, values in missing:
        print(f"  CHYBÍ DB [{key}]: {', '.join(values)}")
    for key, rows in sorted(duplicate_ids.items()):
        print(f"  DUPLICITA [{key}]: " + ", ".join(f"{name} (ID {ident})" for ident, name in rows))
    return int(bool(outside or missing or duplicate_ids))


if __name__ == "__main__":
    raise SystemExit(main())
