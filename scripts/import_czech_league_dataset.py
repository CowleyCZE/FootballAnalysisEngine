#!/usr/bin/env python3
"""Import the finished Chance Liga dataset, including results and match statistics."""
from __future__ import annotations

import argparse
import csv
import math
import sqlite3
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CSV = REPO_ROOT / "database" / "data_csv" / "czech_league_xg_dataset.csv"
import sys
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.database.schema import initialize_database
from app.database.team_identity import get_or_create_team
from app.statistics.history_autofill import resolve_team_key

TZ = ZoneInfo("Europe/Prague")


def _number(row: dict[str, str], name: str) -> float:
    value = (row.get(name) or "").strip()
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise ValueError(f"neplatná nebo záporná hodnota {name}")
    return number


def _integer(row: dict[str, str], name: str) -> int:
    value = _number(row, name)
    if not value.is_integer():
        raise ValueError(f"{name} není celé číslo")
    return int(value)


def _parse_row(row: dict[str, str], line: int) -> dict:
    day = date.fromisoformat((row.get("date") or "").strip())
    kickoff = time.fromisoformat((row.get("kickoff_time") or "").strip())
    home, away = (row.get("home_team") or "").strip(), (row.get("away_team") or "").strip()
    if not home or not away or resolve_team_key(home) == resolve_team_key(away):
        raise ValueError("chybí tým nebo jsou domácí a hosté totožní")
    if (row.get("status") or "").strip().casefold() != "finished":
        raise ValueError("zápas nemá stav Finished")
    hg, ag = _integer(row, "home_goals"), _integer(row, "away_goals")
    hh, ah = _integer(row, "ht_home_goals"), _integer(row, "ht_away_goals")
    if hh > hg or ah > ag:
        raise ValueError("poločasové skóre převyšuje konečný stav")
    hxg, axg = _number(row, "home_xg"), _number(row, "away_xg")
    hsot, asot = _integer(row, "home_shots_on_target"), _integer(row, "away_shots_on_target")
    hp, ap = _number(row, "home_possession_pct"), _number(row, "away_possession_pct")
    hr, ar = _integer(row, "home_red_cards"), _integer(row, "away_red_cards")
    if hxg > 8 or axg > 8 or hp > 100 or ap > 100 or hr > 2 or ar > 2:
        raise ValueError("xG, držení míče nebo červené karty jsou mimo povolený rozsah")
    if not 98 <= hp + ap <= 102:
        raise ValueError("součet držení míče je mimo toleranci 100±2 %")
    local = datetime.combine(day, kickoff, TZ)
    season_start = day.year if day.month >= 7 else day.year - 1
    return {"line": line, "date": day.isoformat(), "home": home, "away": away,
            "scheduled_at": local.astimezone(ZoneInfo("UTC")).isoformat(),
            "competition": (row.get("competition") or "Chance Liga").strip(),
            "season": f"{season_start}-{season_start + 1}", "home_goals": hg, "away_goals": ag,
            "home_ht_goals": hh, "away_ht_goals": ah, "home_xg": hxg, "away_xg": axg,
            "home_shots_on_target": hsot, "away_shots_on_target": asot,
            "home_possession": hp, "away_possession": ap, "home_red_cards": hr,
            "away_red_cards": ar}


def import_dataset(csv_path: Path = DEFAULT_CSV, db_path: Path = REPO_ROOT / "database" / "football.db") -> dict:
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"date", "kickoff_time", "competition", "home_team", "away_team", "home_goals", "away_goals",
                    "ht_home_goals", "ht_away_goals", "home_xg", "away_xg", "home_shots_on_target",
                    "away_shots_on_target", "home_possession_pct", "away_possession_pct", "home_red_cards",
                    "away_red_cards", "status"}
        missing = required - set(reader.fieldnames or ())
        if missing:
            raise ValueError("CSV nemá sloupce: " + ", ".join(sorted(missing)))
        rows = []
        errors = []
        for line, raw in enumerate(reader, start=2):
            try:
                rows.append(_parse_row(raw, line))
            except (ValueError, TypeError) as exc:
                errors.append(f"řádek {line}: {exc}")
    if errors:
        raise ValueError("Import zastaven bez zápisu; neplatné řádky: " + "; ".join(errors[:20]))
    if not rows:
        raise ValueError("CSV neobsahuje žádné zápasy")
    keys = [(r["date"], r["home"], r["away"]) for r in rows]
    if len(keys) != len(set(keys)):
        raise ValueError("CSV obsahuje duplicitní zápas")

    initialize_database(str(db_path))
    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        team_keys = {resolve_team_key(name): int(team_id)
                     for team_id, name in conn.execute("SELECT id,name FROM teams")}

        def get_team(name: str) -> int:
            key = resolve_team_key(name)
            if key in team_keys:
                return team_keys[key]
            team_keys[key] = get_or_create_team(conn, name, "Chance Liga")
            return team_keys[key]

        comp_ids = {str(name).casefold(): int(ident)
                    for ident, name in conn.execute("SELECT id,name FROM competitions")}
        inserted = updated = 0
        for row in rows:
            hid, aid = get_team(row["home"]), get_team(row["away"])
            competition_id = comp_ids.get(row["competition"].casefold())
            if competition_id is None:
                competition_id = int(conn.execute("INSERT INTO competitions(name,country) VALUES(?,?)",
                                                   (row["competition"], "Czechia")).lastrowid)
                comp_ids[row["competition"].casefold()] = competition_id
            local_start = datetime.combine(date.fromisoformat(row["date"]), time.min, TZ).astimezone(ZoneInfo("UTC")).isoformat()
            local_end = (datetime.combine(date.fromisoformat(row["date"]), time.min, TZ)
                         + timedelta(days=1)).astimezone(ZoneInfo("UTC")).isoformat()
            existing = conn.execute("""SELECT id FROM matches
                WHERE home_team_id=? AND away_team_id=?
                  AND julianday(scheduled_at)>=julianday(?) AND julianday(scheduled_at)<julianday(?)
                ORDER BY ABS(julianday(scheduled_at)-julianday(?)) LIMIT 1""",
                (hid, aid, local_start, local_end, row["scheduled_at"])).fetchone()
            if existing:
                match_id = int(existing[0]); updated += 1
                conn.execute("""UPDATE matches SET competition_id=?,competition=?,season=?,scheduled_at=?,kickoff_time_known=1,kickoff_time_source=?,status='RESOLVED',updated_at=CURRENT_TIMESTAMP WHERE id=?""",
                             (competition_id, row["competition"], row["season"], row["scheduled_at"], csv_path.name, match_id))
            else:
                match_id = int(conn.execute("""INSERT INTO matches
                    (competition_id,competition,season,home_team_id,away_team_id,scheduled_at,kickoff_time_known,kickoff_time_source,status)
                    VALUES(?,?,?,?,?,?,1,?,'RESOLVED')""",
                    (competition_id, row["competition"], row["season"], hid, aid, row["scheduled_at"], csv_path.name)).lastrowid)
                inserted += 1
            conn.execute("""INSERT INTO match_statistics
                (match_id,home_goals,away_goals,home_ht_goals,away_ht_goals,home_ft_goals,away_ft_goals,
                 home_shots_on_target,away_shots_on_target,home_possession,away_possession,home_red_cards,
                 away_red_cards,home_xg,away_xg,home_xga,away_xga,xg_metric_definition)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(match_id) DO UPDATE SET
                 home_goals=excluded.home_goals,away_goals=excluded.away_goals,
                 home_ht_goals=excluded.home_ht_goals,away_ht_goals=excluded.away_ht_goals,
                 home_ft_goals=excluded.home_ft_goals,away_ft_goals=excluded.away_ft_goals,
                 home_shots_on_target=excluded.home_shots_on_target,away_shots_on_target=excluded.away_shots_on_target,
                 home_possession=excluded.home_possession,away_possession=excluded.away_possession,
                 home_red_cards=excluded.home_red_cards,away_red_cards=excluded.away_red_cards,
                 home_xg=excluded.home_xg,away_xg=excluded.away_xg,home_xga=excluded.home_xga,away_xga=excluded.away_xga,
                 xg_metric_definition=excluded.xg_metric_definition,updated_at=CURRENT_TIMESTAMP""",
                (match_id,row["home_goals"],row["away_goals"],row["home_ht_goals"],row["away_ht_goals"],
                 row["home_goals"],row["away_goals"],row["home_shots_on_target"],row["away_shots_on_target"],
                 row["home_possession"],row["away_possession"],row["home_red_cards"],row["away_red_cards"],
                 row["home_xg"],row["away_xg"],row["away_xg"],row["home_xg"],"Opta xG (czech_league_xg_dataset.csv)"))
            # These exact fixtures are now canonical match_statistics rows; remove their earlier xG-only staging copies.
            conn.execute("DELETE FROM match_xg_observations WHERE match_date=? AND home_team_id=? AND away_team_id=?",
                         (row["date"], hid, aid))
        # The earlier sparse xG CSV used the old club label Lišeň for Artis Brno;
        # all entries from that superseded source are replaced by this full dataset.
        conn.execute("DELETE FROM match_xg_observations WHERE source_file='zapasy_xg.csv' AND competition='Chance Liga'")
        conn.commit()
    return {"rows": len(rows), "inserted": inserted, "updated": updated,
            "teams": len(team_keys), "matches": len(rows), "invalid": 0}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    parser.add_argument("--db", type=Path, default=REPO_ROOT / "database" / "football.db")
    args = parser.parse_args()
    result = import_dataset(args.csv, args.db)
    print(f"Import hotov: {result['rows']} zápasů, nově {result['inserted']}, aktualizováno {result['updated']}; týmů v DB {result['teams']}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
