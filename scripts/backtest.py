#!/usr/bin/env python3
"""Backtest statistického modelu na odehraných zápasech z historie (jen čtení DB).

Pro každý odehraný zápas se predikce spočítá jen z dat před jeho výkopem
(žádný únik dat) a porovná se se skutečným výsledkem. Výstup: přesnost
přesného skóre, přesnost 1-X-2 a log-loss 1-X-2 (spolu s naivními základnami).

Použití:
    python scripts/backtest.py [--db database/football.db] [--competition "Liga"]
                               [--min-history 3] [--limit 200]
"""
from __future__ import annotations

import argparse
import math
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.statistics.repository import StatisticsRepository  # noqa: E402
from app.statistics.score_predictor import ExactScorePredictor  # noqa: E402

EPS = 1e-12


class ReadOnlyStatisticsRepository(StatisticsRepository):
    """Stejné dotazy jako produkční repozitář, ale DB se otevírá pouze pro čtení."""

    def __init__(self, db_path: str):
        self.db_path = db_path  # záměrně bez initialize_database (ta by DB mohla měnit)

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(f"file:{Path(self.db_path).resolve()}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        return conn


def _outcome(home: int, away: int) -> str:
    return "H" if home > away else "D" if home == away else "A"


def _played_matches(repo: ReadOnlyStatisticsRepository, competition: Optional[str]) -> List[Dict[str, Any]]:
    sql = (
        "SELECT m.id AS match_id, m.home_team_id, m.away_team_id, m.scheduled_at, "
        "ms.home_goals, ms.away_goals "
        "FROM matches m JOIN match_statistics ms ON ms.match_id = m.id "
        "LEFT JOIN competitions c ON c.id = m.competition_id "
        "WHERE ms.home_goals IS NOT NULL AND ms.away_goals IS NOT NULL AND m.scheduled_at IS NOT NULL"
    )
    params: List[Any] = []
    if competition:
        sql += " AND COALESCE(c.name, m.competition) = ?"
        params.append(competition)
    sql += " ORDER BY m.scheduled_at"
    conn = repo._get_connection()
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def run_backtest(db_path: str, competition: Optional[str] = None, min_history: int = 3,
                 limit: Optional[int] = None) -> Dict[str, Any]:
    """Spočítá metriky; zápasy, kde některý tým nemá aspoň `min_history` zápasů před výkopem, přeskočí."""
    repo = ReadOnlyStatisticsRepository(db_path)
    matches = _played_matches(repo, competition)
    if limit:
        matches = matches[-int(limit):]

    evaluated = skipped = exact_hits = outcome_hits = 0
    log_loss_sum = 0.0
    home_baseline_hits = 0
    goal_abs_error = 0.0

    for m in matches:
        kickoff = m["scheduled_at"]
        home_id, away_id = int(m["home_team_id"]), int(m["away_team_id"])
        home_rows = repo.get_team_recent_matches(home_id, kickoff, limit=20, before_kickoff=kickoff)
        away_rows = repo.get_team_recent_matches(away_id, kickoff, limit=20, before_kickoff=kickoff)
        if len(home_rows) < min_history or len(away_rows) < min_history:
            skipped += 1
            continue
        h2h = repo.get_head_to_head(home_id, away_id, kickoff, limit=8, before_kickoff=kickoff)
        history = {int(r["match_id"]): r for r in home_rows + away_rows}
        ordered = sorted(history.values(), key=lambda r: str(r.get("scheduled_at") or ""), reverse=True)
        pred = ExactScorePredictor.predict(
            ordered, home_id, away_id, h2h_rows=h2h,
            league_stats=repo.get_league_goal_stats(int(m["match_id"]), kickoff),
            league_rows=repo.get_league_matches(int(m["match_id"]), kickoff),
        )
        if not pred:
            skipped += 1
            continue

        actual_h, actual_a = int(m["home_goals"]), int(m["away_goals"])
        actual = _outcome(actual_h, actual_a)
        probs = {"H": pred["home_win_probability"], "D": pred["draw_probability"], "A": pred["away_win_probability"]}
        evaluated += 1
        exact_hits += int((pred["predicted_home_goals"], pred["predicted_away_goals"]) == (actual_h, actual_a))
        outcome_hits += int(max(probs, key=probs.get) == actual)
        home_baseline_hits += int(actual == "H")
        log_loss_sum += -math.log(max(probs[actual], EPS))
        goal_abs_error += (abs(pred["expected_home_goals"] - actual_h) + abs(pred["expected_away_goals"] - actual_a)) / 2

    def ratio(x: float) -> Optional[float]:
        return round(x / evaluated, 4) if evaluated else None

    return {
        "matches_total": len(matches),
        "evaluated": evaluated,
        "skipped_insufficient_history": skipped,
        "exact_score_accuracy": ratio(exact_hits),
        "outcome_1x2_accuracy": ratio(outcome_hits),
        "log_loss_1x2": ratio(log_loss_sum),
        "mean_abs_goal_error": ratio(goal_abs_error),
        "baseline_always_home_accuracy": ratio(home_baseline_hits),
        "baseline_uniform_log_loss": round(math.log(3), 4) if evaluated else None,
        "model_version": ExactScorePredictor.MODEL_VERSION,
    }


def _fmt(value: Any, percent: bool = False) -> str:
    if value is None:
        return "n/a"
    return f"{value * 100:.1f} %" if percent else f"{value:.4f}"


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Backtest statistického modelu (jen čtení DB).")
    parser.add_argument("--db", default="database/football.db")
    parser.add_argument("--competition", default=None)
    parser.add_argument("--min-history", type=int, default=3)
    parser.add_argument("--limit", type=int, default=None, help="Vyhodnotit jen posledních N zápasů")
    args = parser.parse_args(argv)

    if not Path(args.db).exists():
        print(f"Databáze '{args.db}' neexistuje.", file=sys.stderr)
        return 2
    r = run_backtest(args.db, args.competition, args.min_history, args.limit)
    print(f"Model: {r['model_version']}")
    print(f"Zápasů v DB: {r['matches_total']}, vyhodnoceno: {r['evaluated']}, "
          f"přeskočeno (málo historie): {r['skipped_insufficient_history']}")
    if not r["evaluated"]:
        print("Není co vyhodnotit – naimportujte historii (scripts/import_history_csv.py).")
        return 1
    print(f"Přesné skóre:        {_fmt(r['exact_score_accuracy'], True)}")
    print(f"1-X-2 přesnost:      {_fmt(r['outcome_1x2_accuracy'], True)} "
          f"(základna „vždy domácí“: {_fmt(r['baseline_always_home_accuracy'], True)})")
    print(f"Log-loss 1-X-2:      {_fmt(r['log_loss_1x2'])} (základna rovnoměrně: {_fmt(r['baseline_uniform_log_loss'])})")
    print(f"Prům. abs. chyba gólů: {_fmt(r['mean_abs_goal_error'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
