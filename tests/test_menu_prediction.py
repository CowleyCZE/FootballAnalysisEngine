"""TODO 1.5 – menu (volba 4) vypisuje top-3 skóre a upozornění na prior."""
import json
import sqlite3

import menu
from app.database.schema import initialize_database


def test_menu_shows_top3_scores_and_prior_warning(tmp_path, monkeypatch, capsys):
    db_path = tmp_path / "menu-pred.db"
    initialize_database(str(db_path))
    monkeypatch.setattr(menu, "DB_PATH", str(db_path))
    scores = {"1-1": 0.12, "0-0": 0.08, "2-1": 0.15, "1-0": 0.11}
    with sqlite3.connect(db_path) as conn:
        conn.execute("INSERT INTO teams(id, name, normalized_name) VALUES (1, 'Sparta', 'sparta'), (2, 'Slavia', 'slavia')")
        conn.execute("INSERT INTO matches(id, competition, home_team_id, away_team_id, scheduled_at, status) VALUES (1, 'Liga', 1, 2, '2026-11-10T18:00:00+00:00', 'RESOLVED')")
        conn.execute("INSERT INTO runs(id, run_id, status, started_at) VALUES (1, 'RUN-1', 'RUNNING', '2026-11-01T10:00:00Z')")
        conn.execute(
            "INSERT INTO pipeline_runs(run_id, match_id, state, cycle, max_cycles, started_at, updated_at) "
            "VALUES ('RUN-1', 1, 'COMPLETED', 1, 3, '2026-11-01T10:00:00Z', '2026-11-01T10:01:00Z')"
        )
        conn.execute(
            """INSERT INTO match_predictions(match_id, run_id, data_cutoff_at, model_version,
                   expected_home_goals, expected_away_goals, predicted_home_goals, predicted_away_goals,
                   home_win_probability, draw_probability, away_win_probability,
                   score_probabilities_json, sample_size, factors_json)
               VALUES (1, 'RUN-1', '2026-11-01T10:00:00+00:00', 'poisson-dc-context-v4', 1.7, 1.1, 2, 1,
                       0.5, 0.25, 0.25, ?, 3, ?)""",
            (json.dumps(scores), json.dumps({"prior_only": True})),
        )

    monkeypatch.setattr("builtins.input", lambda _prompt="": "1")
    menu.show_analysis_results()
    out = capsys.readouterr().out

    assert "Top-3 skóre: 2:1 (15.0%), 1:1 (12.0%), 1:0 (11.0%)" in out
    assert "0:0" not in out.split("Top-3 skóre:")[1].splitlines()[0]
    assert "Pouze prior" in out
