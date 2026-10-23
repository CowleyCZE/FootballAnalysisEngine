#!/usr/bin/env python3
"""Import historical football results into the local SQLite database.

Accepted column aliases include football-data.co.uk (Date, HomeTeam, AwayTeam,
FTHG, FTAG) and the project's normalized names. Optional xG/xGA columns are
stored when present; missing advanced metrics remain NULL and are reported.
"""
from __future__ import annotations

import argparse
import csv
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.database.schema import initialize_database
from app.statistics.history_autofill import resolve_team_key


def value(row: dict[str, str], *names: str) -> str:
    normalized = {str(k).strip().lower().replace(" ", "_"): (v or "").strip() for k, v in row.items()}
    for name in names:
        val = normalized.get(name.lower().replace(" ", "_"), "")
        if val != "":
            return val
    return ""


def number(text: str) -> float | None:
    if not text:
        return None
    try:
        return float(text.replace(",", "."))
    except ValueError:
        return None


def goals(text: str) -> int | None:
    val = number(text)
    return int(val) if val is not None and val.is_integer() else None


def parse_date(text: str, timezone_name: str) -> str:
    text = text.strip()
    formats = ("%d/%m/%y", "%d/%m/%Y", "%Y-%m-%d", "%Y-%m-%d %H:%M", "%d.%m.%Y")
    dt = None
    for fmt in formats:
        try:
            dt = datetime.strptime(text, fmt)
            break
        except ValueError:
            continue
    if dt is None:
        raise ValueError(f"Neznámý formát data '{text}'")
    return dt.replace(tzinfo=ZoneInfo(timezone_name)).astimezone(ZoneInfo("UTC")).isoformat()


def import_csv(csv_path: Path, db_path: Path, competition: str, timezone_name: str) -> tuple[int, int, int]:
    initialize_database(str(db_path))
    inserted = skipped = missing_xg = 0
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle, sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError("CSV nemá hlavičku.")
        for line, row in enumerate(reader, start=2):
            home = value(row, "home_team", "hometeam")
            away = value(row, "away_team", "awayteam")
            date = value(row, "date", "scheduled_at", "match_date")
            home_goals = goals(value(row, "home_goals", "fthg", "fthg"))
            away_goals = goals(value(row, "away_goals", "ftag", "ftag"))
            if not home or not away or not date or home_goals is None or away_goals is None:
                skipped += 1
                print(f"Přeskakuji řádek {line}: chybí týmy, datum nebo konečný výsledek.")
                continue
            scheduled_at = parse_date(date, timezone_name)
            home_xg = number(value(row, "home_xg", "xg_home", "hxg"))
            away_xg = number(value(row, "away_xg", "xg_away", "axg"))
            home_xga = number(value(row, "home_xga", "xga_home", "hxga"))
            away_xga = number(value(row, "away_xga", "xga_away", "axga"))
            if home_xg is None or away_xg is None:
                missing_xg += 1

            def team_id(name: str) -> int:
                norm = " ".join(name.lower().split())
                # Shoda přes kanonický klíč + aliasy (stejně jako history_autofill), ať nevznikají duplicity týmů.
                key = resolve_team_key(name)
                if key:
                    for ident, existing in conn.execute("SELECT id, name FROM teams ORDER BY id").fetchall():
                        if resolve_team_key(existing) == key:
                            return int(ident)
                row_team = conn.execute("SELECT id FROM teams WHERE normalized_name=?", (norm,)).fetchone()
                if row_team:
                    return int(row_team[0])
                cur = conn.execute("INSERT INTO teams(name, normalized_name) VALUES (?, ?)", (name, norm))
                return int(cur.lastrowid)

            home_id, away_id = team_id(home), team_id(away)
            comp = conn.execute("SELECT id FROM competitions WHERE lower(name)=lower(?)", (competition,)).fetchone()
            comp_id = int(comp[0]) if comp else int(conn.execute("INSERT INTO competitions(name) VALUES (?)", (competition,)).lastrowid)
            existing = conn.execute("SELECT id FROM matches WHERE home_team_id=? AND away_team_id=? AND scheduled_at=?", (home_id, away_id, scheduled_at)).fetchone()
            match_id = int(existing[0]) if existing else int(conn.execute("INSERT INTO matches(home_team_id, away_team_id, competition_id, competition, scheduled_at, status) VALUES (?,?,?,?,?,'RESOLVED')", (home_id, away_id, comp_id, competition, scheduled_at)).lastrowid)
            conn.execute("""INSERT INTO match_statistics(match_id, home_goals, away_goals, home_xg, away_xg, home_xga, away_xga)
                VALUES (?,?,?,?,?,?,?) ON CONFLICT(match_id) DO UPDATE SET home_goals=excluded.home_goals, away_goals=excluded.away_goals,
                home_xg=excluded.home_xg, away_xg=excluded.away_xg, home_xga=excluded.home_xga, away_xga=excluded.away_xga""",
                (match_id, home_goals, away_goals, home_xg, away_xg, home_xga, away_xga))
            inserted += 1
        conn.commit()
    return inserted, skipped, missing_xg


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", required=True, type=Path)
    parser.add_argument("--competition", required=True)
    parser.add_argument("--timezone", default="Europe/Prague")
    parser.add_argument("--db", default="database/football.db", type=Path)
    args = parser.parse_args()
    inserted, skipped, missing_xg = import_csv(args.csv, args.db, args.competition, args.timezone)
    print(f"Import dokončen: {inserted} zápasů, {skipped} přeskočených řádků, {missing_xg} zápasů bez xG.")
    if inserted < 10:
        print("Upozornění: pro stabilnější formu a recency weighting doporučuji alespoň 10 zápasů na tým.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
