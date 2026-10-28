"""Import xG z CSV (zdroj-agnostický) do `match_statistics` (TODO 11.10, bod 1).

Model už xG používá (`home_xg`/`away_xg` ve vzorku), ale data chyběla (coverage 0 %). Modul jen
doplní xG k ZÁPASŮM, které v DB už existují a mají výsledek; nikdy nevytváří zápasy a nedomýšlí
hodnoty. Zdroj dat si určuje uživatel (strukturovaný export z poskytovatele s licencí/oprávněním
ke stažení) – název zdroje se uloží do `xg_metric_definition`.

CSV (oddělovač , nebo ;, hlavička povinná):
    date,home_team,away_team,home_xg,away_xg[,home_npxg,away_npxg]
    2026-10-17,Slavia Praha,Sparta Praha,1.84,0.92

Použití:
    python -m app.statistics.xg_import soubor.csv --source "nazev-zdroje" [--dry-run] [--overwrite]
"""
from __future__ import annotations

import argparse
import csv
import io
import math
import re
import sqlite3
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence

from app.database.schema import initialize_database
from app.statistics.history_autofill import canonical_team_key, resolve_team_key
from app.statistics.team_features import derive_npxg

MAX_XG = 8.0
DAY_TOLERANCE = 1  # rozdíl dnů mezi datem v CSV a zápasem v DB (časové pásmo, přesun výkopu)

_REQUIRED = ("date", "home_team", "away_team", "home_xg", "away_xg")


def _team_key(name: str) -> str:
    return resolve_team_key(name) or canonical_team_key(name)


def _parse_date(value: str) -> Optional[datetime]:
    text = str(value or "").strip()
    for fmt, size in (("%Y-%m-%d", 10), ("%d.%m.%Y", 10), ("%d/%m/%Y", 10)):
        try:
            return datetime.strptime(text[:size], fmt)
        except ValueError:
            continue
    return None


def _parse_xg(value: Any) -> Optional[float]:
    text = str(value if value is not None else "").strip().replace(",", ".")
    if not text:
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    return number if math.isfinite(number) and 0.0 <= number <= MAX_XG else None


def _parse_count(value: Any) -> Optional[int]:
    text = str(value if value is not None else "").strip()
    if not text:
        return None
    try:
        count = int(text)
    except ValueError:
        return None
    return count if 0 <= count <= 20 else None


def parse_csv(text: str) -> List[Dict[str, Any]]:
    """Načte řádky CSV; neplatné řádky vrací s klíčem `error` (nikdy nehádá hodnoty)."""
    sample = text[:2048]
    delimiter = ";" if sample.count(";") > sample.count(",") else ","
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    fields = {(f or "").strip().lower() for f in (reader.fieldnames or [])}
    missing = [c for c in _REQUIRED if c not in fields]
    if missing:
        raise ValueError(f"CSV postrádá sloupce: {', '.join(missing)}")
    rows: List[Dict[str, Any]] = []
    for index, raw in enumerate(reader, start=2):
        row = {(k or "").strip().lower(): (v or "").strip() for k, v in raw.items()}
        parsed = _parse_date(row["date"])
        hx, ax = _parse_xg(row["home_xg"]), _parse_xg(row["away_xg"])
        item: Dict[str, Any] = {
            "line": index, "date": parsed, "home_team": row["home_team"], "away_team": row["away_team"],
            "home_xg": hx, "away_xg": ax,
            "home_npxg": _parse_xg(row.get("home_npxg", "")), "away_npxg": _parse_xg(row.get("away_npxg", "")),
            "home_gs_adj_xg": _parse_xg(row.get("home_gs_adj_xg", row.get("home_game_state_adjusted_xg", ""))),
            "away_gs_adj_xg": _parse_xg(row.get("away_gs_adj_xg", row.get("away_game_state_adjusted_xg", ""))),
            "home_penalties": _parse_count(row.get("home_penalties", row.get("home_penalty_attempts", ""))),
            "away_penalties": _parse_count(row.get("away_penalties", row.get("away_penalty_attempts", ""))),
        }
        home_penalty_xg, away_penalty_xg = _parse_xg(row.get("home_penalty_xg")), _parse_xg(row.get("away_penalty_xg"))
        if item["home_npxg"] is None:
            item["home_npxg"] = derive_npxg(hx, item["home_penalties"], home_penalty_xg)
        if item["away_npxg"] is None:
            item["away_npxg"] = derive_npxg(ax, item["away_penalties"], away_penalty_xg)
        item["npxg_estimated"] = (
            (_parse_xg(row.get("home_npxg", "")) is None and item["home_penalties"] is not None and home_penalty_xg is None)
            or (_parse_xg(row.get("away_npxg", "")) is None and item["away_penalties"] is not None and away_penalty_xg is None)
        )
        if parsed is None:
            item["error"] = "neplatné datum"
        elif not row["home_team"] or not row["away_team"]:
            item["error"] = "chybí tým"
        elif hx is None or ax is None:
            item["error"] = "neplatné xG (0–8, číslo)"
        rows.append(item)
    return rows


def import_xg(csv_path: str, db_path: str = "database/football.db", source: str = "csv_import",
              dry_run: bool = False, overwrite: bool = False) -> Dict[str, Any]:
    with open(csv_path, "r", encoding="utf-8-sig") as handle:
        rows = parse_csv(handle.read())
    return import_xg_rows(rows, db_path, source=source, dry_run=dry_run, overwrite=overwrite)


def import_xg_rows(rows: Sequence[Dict[str, Any]], db_path: str, source: str = "csv_import",
                   dry_run: bool = False, overwrite: bool = False) -> Dict[str, Any]:
    initialize_database(db_path)
    result: Dict[str, Any] = {"rows": len(rows), "updated": 0, "skipped_existing": 0, "invalid": 0,
                              "unmatched": 0, "already_imported": 0, "problems": []}
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        key_to_ids: Dict[str, List[int]] = {}
        for team in conn.execute("SELECT id, name FROM teams").fetchall():
            key_to_ids.setdefault(_team_key(team["name"]), []).append(int(team["id"]))

        for row in rows:
            if row.get("error"):
                result["invalid"] += 1
                result["problems"].append(f"řádek {row['line']}: {row['error']}")
                continue
            home_ids = key_to_ids.get(_team_key(row["home_team"]), [])
            away_ids = key_to_ids.get(_team_key(row["away_team"]), [])
            match = None
            if home_ids and away_ids:
                day = row["date"].strftime("%Y-%m-%d")
                # A complete result dataset may already contain this fixture under a newer
                # opponent label. Avoid recreating a duplicate xG-only observation in that case.
                completed_with_xg = conn.execute(
                    f"SELECT 1 FROM matches m JOIN match_statistics ms ON ms.match_id=m.id "
                    f"WHERE m.home_team_id IN ({','.join('?' * len(home_ids))}) "
                    f"AND m.competition='Chance Liga' AND ms.home_goals IS NOT NULL "
                    f"AND ms.away_goals IS NOT NULL AND ms.home_xg IS NOT NULL "
                    f"AND ABS(julianday(date(m.scheduled_at))-julianday(?))<=? LIMIT 1",
                    (*home_ids, day, DAY_TOLERANCE),
                ).fetchone()
                if completed_with_xg:
                    result["already_imported"] += 1
                    continue
                match = conn.execute(
                    f"SELECT m.id, ms.home_xg, ms.xg_metric_definition, ms.home_npxg, ms.away_npxg, "
                    f"ms.home_gs_adj_xg, ms.away_gs_adj_xg FROM matches m "
                    f"JOIN match_statistics ms ON ms.match_id = m.id "
                    f"WHERE m.home_team_id IN ({','.join('?' * len(home_ids))}) "
                    f"AND m.away_team_id IN ({','.join('?' * len(away_ids))}) "
                    f"AND ms.home_goals IS NOT NULL AND ms.away_goals IS NOT NULL "
                    f"AND ABS(julianday(date(m.scheduled_at)) - julianday(?)) <= ? "
                    f"ORDER BY ABS(julianday(date(m.scheduled_at)) - julianday(?)) LIMIT 1",
                    (*home_ids, *away_ids, day, DAY_TOLERANCE, day),
                ).fetchone()
            if match is None:
                result["unmatched"] += 1
                if len(result["problems"]) < 25:
                    result["problems"].append(
                        f"řádek {row['line']}: zápas {row['home_team']} – {row['away_team']} "
                        f"({row['date']:%Y-%m-%d}) není v DB s výsledkem")
                continue
            protect_existing_xg = (match["home_xg"] is not None and not overwrite
                                   and match["xg_metric_definition"] != source)
            if protect_existing_xg and not any(row.get(k) is not None for k in
                    ("home_npxg", "away_npxg", "home_gs_adj_xg", "away_gs_adj_xg")):
                result["skipped_existing"] += 1
                continue
            if not dry_run:
                if protect_existing_xg:
                    conn.execute(
                        "UPDATE match_statistics SET home_npxg=COALESCE(?, home_npxg), "
                        "away_npxg=COALESCE(?, away_npxg), home_gs_adj_xg=COALESCE(?, home_gs_adj_xg), "
                        "away_gs_adj_xg=COALESCE(?, away_gs_adj_xg), updated_at=CURRENT_TIMESTAMP WHERE match_id=?",
                        (row["home_npxg"], row["away_npxg"], row["home_gs_adj_xg"],
                         row["away_gs_adj_xg"], int(match["id"])),
                    )
                else:
                    conn.execute(
                        "UPDATE match_statistics SET home_xg=?, away_xg=?, home_xga=?, away_xga=?, "
                        "home_npxg=COALESCE(?, home_npxg), away_npxg=COALESCE(?, away_npxg), "
                        "home_gs_adj_xg=COALESCE(?, home_gs_adj_xg), away_gs_adj_xg=COALESCE(?, away_gs_adj_xg), "
                        "xg_metric_definition=?, updated_at=CURRENT_TIMESTAMP WHERE match_id=?",
                        (row["home_xg"], row["away_xg"], row["away_xg"], row["home_xg"],
                         row["home_npxg"], row["away_npxg"], row["home_gs_adj_xg"], row["away_gs_adj_xg"],
                        source + ("+npxg-penalty-estimate-0.79" if row.get("npxg_estimated") else ""), int(match["id"])),
                    )
            result["updated"] += 1
        if not dry_run:
            conn.commit()
    result["problems"] = result["problems"][:25]
    result["dry_run"] = dry_run
    return result


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Import xG z CSV do match_statistics")
    parser.add_argument("csv_path")
    parser.add_argument("--db", default="database/football.db")
    parser.add_argument("--source", required=True, help="Název zdroje (uloží se do xg_metric_definition)")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--overwrite", action="store_true", help="Přepsat xG z jiného zdroje")
    args = parser.parse_args(argv)
    result = import_xg(args.csv_path, args.db, args.source, args.dry_run, args.overwrite)
    print(f"xG import ({'dry-run' if result['dry_run'] else 'zapsáno'}): řádků {result['rows']}, "
          f"aktualizováno {result['updated']}, přeskočeno (jiný zdroj) {result['skipped_existing']}, "
          f"neplatných {result['invalid']}, nenalezeno v DB {result['unmatched']}")
    for line in result["problems"]:
        print("  !", line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
