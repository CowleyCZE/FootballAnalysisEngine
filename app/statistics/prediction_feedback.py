"""Vyhodnocení uložených předzápasových predikcí proti skutečným výsledkům."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any


def prediction_feedback(db_path: str | Path) -> dict[str, Any]:
    """Read-only report; scores only predictions created before kickoff."""
    uri = f"file:{Path(db_path).resolve()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("""
            WITH eligible AS (
                SELECT p.*,m.scheduled_at,m.home_team_id,m.away_team_id,
                       s.home_goals AS actual_home,s.away_goals AS actual_away,
                       h.name AS home_name,a.name AS away_name,
                       ROW_NUMBER() OVER (PARTITION BY p.match_id ORDER BY p.created_at DESC,p.id DESC) AS rank
                FROM match_predictions p
                JOIN matches m ON m.id=p.match_id
                JOIN match_statistics s ON s.match_id=m.id
                LEFT JOIN teams h ON h.id=m.home_team_id
                LEFT JOIN teams a ON a.id=m.away_team_id
                WHERE s.home_goals IS NOT NULL AND s.away_goals IS NOT NULL
                  AND julianday(p.created_at) <= julianday(m.scheduled_at)
            )
            SELECT * FROM eligible WHERE rank=1 ORDER BY scheduled_at DESC,match_id DESC
        """).fetchall()

    evaluated = []
    for row in rows:
        actual = 0 if row["actual_home"] > row["actual_away"] else 1 if row["actual_home"] == row["actual_away"] else 2
        probabilities = [float(row["home_win_probability"]), float(row["draw_probability"]),
                         float(row["away_win_probability"])]
        brier = sum((p - (1.0 if i == actual else 0.0)) ** 2 for i, p in enumerate(probabilities))
        expected_home, expected_away = row["expected_home_goals"], row["expected_away_goals"]
        goal_error = ((abs(float(expected_home) - row["actual_home"])
                       + abs(float(expected_away) - row["actual_away"])) / 2
                      if expected_home is not None and expected_away is not None else None)
        evaluated.append({
            "match_id": int(row["match_id"]), "scheduled_at": row["scheduled_at"],
            "home": row["home_name"] or "?", "away": row["away_name"] or "?",
            "predicted": (int(row["predicted_home_goals"]), int(row["predicted_away_goals"])),
            "actual": (int(row["actual_home"]), int(row["actual_away"])),
            "correct_1x2": max(range(3), key=lambda i: probabilities[i]) == actual,
            "brier": brier,
            "goal_error": goal_error,
            "model_version": row["model_version"],
        })
    count = len(evaluated)
    return {
        "count": count,
        "accuracy_1x2": sum(item["correct_1x2"] for item in evaluated) / count if count else None,
        "brier": sum(item["brier"] for item in evaluated) / count if count else None,
        "exact_score_hit": sum(item["predicted"] == item["actual"] for item in evaluated) / count if count else None,
        "goals_mae": (sum(item["goal_error"] for item in evaluated if item["goal_error"] is not None)
                      / sum(item["goal_error"] is not None for item in evaluated)
                      if any(item["goal_error"] is not None for item in evaluated) else None),
        "matches": evaluated,
    }
