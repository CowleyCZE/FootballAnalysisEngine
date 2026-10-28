"""Import supplied Chance Liga CSV snapshots and dated xG observations."""
from __future__ import annotations

import argparse
import csv
import json
import sqlite3
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.database.schema import initialize_database
from app.database.team_identity import get_or_create_team
from app.statistics.history_autofill import resolve_team_key
from app.statistics.team_features import derive_npxg

SEASON = "2026-2027"
COMPETITION = "Chance Liga"
DATA_DIR = Path(__file__).resolve().parents[2] / "database" / "data_csv"


def _rows(path: Path, delimiter: str = ",") -> List[Dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [{(k or "").strip(): (v or "").strip() for k, v in row.items()}
                for row in csv.DictReader(handle, delimiter=delimiter)]


def _number(value: Any) -> Optional[float]:
    text = str(value or "").strip().replace(",", ".").replace("+", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _team_ids(conn: sqlite3.Connection) -> Dict[str, int]:
    result = {}
    for team_id, name in conn.execute("SELECT id,name FROM teams"):
        result[resolve_team_key(name)] = int(team_id)
    return result


def _get_or_create_team(conn: sqlite3.Connection, ids: Dict[str, int], name: str) -> int:
    key = resolve_team_key(name)
    if key in ids:
        return ids[key]
    ids[key] = get_or_create_team(conn, name, COMPETITION)
    return ids[key]


def _current_league_rows(root: Path) -> Dict[str, Dict[str, float]]:
    path = root / "tabulka_liga.csv"
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        raw = list(csv.reader(handle))
    out: Dict[str, Dict[str, float]] = {}
    for cells in raw[2:]:
        if len(cells) < 20 or not cells[1].strip():
            continue
        name = cells[1].strip()
        if not name:
            continue
        values: Dict[str, float] = {}
        for prefix, offset in (("home", 2), ("away", 11)):
            for col, target in ((0, "matches"), (1, "wins"), (2, "draws"), (3, "losses"),
                                (4, "goals_for"), (5, "goals_against"),
                                (7, "points"), (8, "points_per_match")):
                value = _number(cells[offset + col])
                if value is not None:
                    values[f"{prefix}_{target}"] = value
            n = values.get(f"{prefix}_matches", 0)
            if n:
                values[f"{prefix}_goals_for_per_match"] = values.get(f"{prefix}_goals_for", 0) / n
                values[f"{prefix}_goals_against_per_match"] = values.get(f"{prefix}_goals_against", 0) / n
        out[resolve_team_key(name)] = values
    return out


def _current_team_history(root: Path) -> Dict[str, Dict[str, float]]:
    result: Dict[str, Dict[str, float]] = {}
    for path in (root / "sparta_praha" / "sparta_praha_liga.csv",
                 root / "slavia_praha" / "slavia_praha_ligy.csv"):
        if not path.exists():
            continue
        for row in _rows(path):
            if row.get("Season") != SEASON:
                continue
            key = resolve_team_key(row.get("Squad", ""))
            result[key] = {k.lower(): v for k, source in (
                ("matches", "MP"), ("wins", "W"), ("draws", "D"), ("losses", "L"),
                ("goals_for", "GF"), ("goals_against", "GA"), ("points", "Pts"),
            ) if (v := _number(row.get(source))) is not None}
    return result


def import_football_csvs(db_path: str = "database/football.db", data_dir: Optional[str] = None) -> Dict[str, Any]:
    root = Path(data_dir) if data_dir else DATA_DIR
    initialize_database(db_path)
    xg_path = root / "chance_liga_xg_2026-27.csv"
    match_path = root / "zapasy_xg.csv"
    xg_rows = _rows(xg_path, delimiter=";")
    match_rows = [r for r in _rows(match_path) if r.get("date") and r.get("home_team")]
    standings = _current_league_rows(root)
    history = _current_team_history(root)
    dates = [date.fromisoformat(r["date"]) for r in match_rows]
    cutoff = f"{max(dates).isoformat()}T23:59:59+00:00"
    result = {"season_snapshots": 0, "match_xg_observations": 0, "invalid": [], "cutoff": cutoff}

    with sqlite3.connect(db_path) as conn:
        ids = _team_ids(conn)
        for row in xg_rows:
            if not row.get("Tým"):
                continue
            team_id = _get_or_create_team(conn, ids, row["Tým"])
            metrics: Dict[str, Any] = {}
            for source, target in (("xG_Celkem", "xg_for"), ("xG_Domaci", "xg_for_home"),
                                   ("xG_Hoste", "xg_for_away"), ("xGA_Celkem", "xg_against"),
                                   ("xGA_Domaci", "xg_against_home"), ("xGA_Hoste", "xg_against_away")):
                value = _number(row.get(source))
                if value is None or not 0 <= value <= 8:
                    result["invalid"].append(f"{row.get('Tým')}: neplatná hodnota {source}")
                    break
                metrics[target] = value
            else:
                key = resolve_team_key(row["Tým"])
                metrics.update(standings.get(key, {}))
                metrics.update(history.get(key, {}))
                metrics["matches"] = metrics.get("matches") or metrics.get("home_matches", 0) + metrics.get("away_matches", 0)
                metrics["home_matches"] = metrics.get("home_matches", 0)
                metrics["away_matches"] = metrics.get("away_matches", 0)
                conn.execute("""INSERT INTO team_season_snapshots
                    (team_id,competition,season,data_cutoff_at,source_file,metrics_json)
                    VALUES(?,?,?,?,?,?) ON CONFLICT(team_id,competition,season,data_cutoff_at,source_file)
                    DO UPDATE SET metrics_json=excluded.metrics_json""",
                    (team_id, COMPETITION, SEASON, cutoff,
                     "chance_liga_xg_2026-27.csv+tabulka_liga.csv+team_league_history.csv",
                     json.dumps(metrics, ensure_ascii=False, sort_keys=True)))
                result["season_snapshots"] += 1

        for row in match_rows:
            try:
                match_day = date.fromisoformat(row["date"])
                home_xg, away_xg = _number(row.get("home_xg")), _number(row.get("away_xg"))
                home_npxg, away_npxg = _number(row.get("home_npxg")), _number(row.get("away_npxg"))
                home_gs_adj = _number(row.get("home_gs_adj_xg", row.get("home_game_state_adjusted_xg")))
                away_gs_adj = _number(row.get("away_gs_adj_xg", row.get("away_game_state_adjusted_xg")))
                try:
                    home_penalties = int(row.get("home_penalties", row.get("home_penalty_attempts")))
                except (TypeError, ValueError):
                    home_penalties = None
                try:
                    away_penalties = int(row.get("away_penalties", row.get("away_penalty_attempts")))
                except (TypeError, ValueError):
                    away_penalties = None
                if any(value is not None and not 0 <= value <= 20 for value in (home_penalties, away_penalties)):
                    raise ValueError("neplatný počet penaltových pokusů")
                home_npxg = home_npxg if home_npxg is not None else derive_npxg(home_xg, home_penalties, _number(row.get("home_penalty_xg")))
                away_npxg = away_npxg if away_npxg is not None else derive_npxg(away_xg, away_penalties, _number(row.get("away_penalty_xg")))
                if home_xg is None or away_xg is None or not (0 <= home_xg <= 8 and 0 <= away_xg <= 8):
                    raise ValueError("neplatné xG")
                for value in (home_npxg, away_npxg, home_gs_adj, away_gs_adj):
                    if value is not None and not 0 <= value <= 8:
                        raise ValueError("neplatné odvozené xG")
                home_id = _get_or_create_team(conn, ids, row["home_team"])
                away_id = _get_or_create_team(conn, ids, row["away_team"])
                if home_id == away_id:
                    raise ValueError("domácí a hosté jsou stejný tým")
                conn.execute("""INSERT INTO match_xg_observations
                    (match_date,competition,season,home_team_id,away_team_id,home_xg,away_xg,
                     home_npxg,away_npxg,home_gs_adj_xg,away_gs_adj_xg,source_file)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(match_date,home_team_id,away_team_id,source_file)
                    DO UPDATE SET home_xg=excluded.home_xg,away_xg=excluded.away_xg,
                    home_npxg=excluded.home_npxg,away_npxg=excluded.away_npxg,
                    home_gs_adj_xg=excluded.home_gs_adj_xg,away_gs_adj_xg=excluded.away_gs_adj_xg""",
                    (match_day.isoformat(), COMPETITION, SEASON, home_id, away_id,
                     home_xg, away_xg, home_npxg, away_npxg, home_gs_adj, away_gs_adj, "zapasy_xg.csv"))
                result["match_xg_observations"] += 1
            except (ValueError, KeyError) as exc:
                result["invalid"].append(f"{row.get('date')} {row.get('home_team')}–{row.get('away_team')}: {exc}")
        conn.commit()
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Import supplied Chance Liga xG and standings CSVs")
    parser.add_argument("--db", default="database/football.db")
    parser.add_argument("--data-dir", default=str(DATA_DIR))
    args = parser.parse_args()
    result = import_football_csvs(args.db, args.data_dir)
    print(f"Uloženo sezonních snapshotů: {result['season_snapshots']}; xG zápasů: {result['match_xg_observations']}; cutoff: {result['cutoff']}")
    for error in result["invalid"]:
        print("!", error)
    return 0 if not result["invalid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
