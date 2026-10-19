"""TODO 1.3 – API vrací tip skóre; factors (prior_only) se ukládají do match_predictions."""
import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

import app.api.server as server_module
from app.database.schema import initialize_database
from app.statistics.engine import StatisticalEngine

AUTH = {"X-Worker-Token": "test-secret-token"}
SCORES = {"1-1": 0.12, "0-0": 0.08, "2-1": 0.15, "1-0": 0.11}


@pytest.fixture
def api_db(tmp_path, monkeypatch):
    db_file = str(tmp_path / "api_prediction.db")
    monkeypatch.setattr(server_module, "DB_PATH", db_file)
    monkeypatch.setenv("WORKER_API_TOKEN", "test-secret-token")
    initialize_database(db_file)
    with sqlite3.connect(db_file) as conn:
        conn.execute("INSERT INTO teams(id, name, normalized_name) VALUES (1, 'Real Madrid', 'real_madrid'), (2, 'Barcelona', 'barcelona')")
        conn.execute("INSERT INTO competitions(id, name, country) VALUES (1, 'La Liga', 'Spain')")
        conn.execute("INSERT INTO matches(id, competition, competition_id, home_team_id, away_team_id, scheduled_at, status) VALUES (101, 'La Liga', 1, 1, 2, '2026-10-15T18:00:00+00:00', 'RESOLVED')")
    return db_file


def _start_run(client, db_file):
    run_id = client.post("/api/analysis/start", json={"match_id": 101}, headers=AUTH).json()["run_id"]
    with sqlite3.connect(db_file) as conn:
        cutoff = conn.execute("SELECT data_cutoff_at FROM pipeline_runs WHERE run_id=?", (run_id,)).fetchone()[0]
    return run_id, cutoff


def _insert_prediction(db_file, run_id, cutoff, factors):
    with sqlite3.connect(db_file) as conn:
        conn.execute(
            """INSERT INTO match_predictions(match_id, run_id, data_cutoff_at, model_version,
                   expected_home_goals, expected_away_goals, predicted_home_goals, predicted_away_goals,
                   home_win_probability, draw_probability, away_win_probability,
                   score_probabilities_json, sample_size, factors_json)
               VALUES (101, ?, ?, 'poisson-dc-context-v4', 1.7, 1.1, 2, 1, 0.5, 0.25, 0.25, ?, 10, ?)""",
            (run_id, cutoff, json.dumps(SCORES), json.dumps(factors) if factors is not None else None),
        )


def test_result_contains_prediction(api_db):
    client = TestClient(server_module.app)
    run_id, cutoff = _start_run(client, api_db)
    _insert_prediction(api_db, run_id, cutoff, {"prior_only": True})

    pred = client.get(f"/api/analysis/{run_id}/result", headers=AUTH).json()["prediction"]
    assert pred["predicted_score"] == "2-1"
    assert pred["expected_goals"] == {"home": 1.7, "away": 1.1}
    assert pred["probabilities_1x2"] == {"home_win": 0.5, "draw": 0.25, "away_win": 0.25}
    assert pred["model_version"] == "poisson-dc-context-v4"
    assert pred["sample_size"] == 10
    assert pred["prior_only"] is True
    assert list(pred["top_scores"]) == ["2-1", "1-1", "1-0"]


def test_result_prediction_is_none_without_prediction(api_db):
    client = TestClient(server_module.app)
    run_id, _ = _start_run(client, api_db)
    assert client.get(f"/api/analysis/{run_id}/result", headers=AUTH).json()["prediction"] is None


def test_prior_only_unknown_for_legacy_prediction_without_factors(api_db):
    client = TestClient(server_module.app)
    run_id, cutoff = _start_run(client, api_db)
    _insert_prediction(api_db, run_id, cutoff, None)
    pred = client.get(f"/api/analysis/{run_id}/result", headers=AUTH).json()["prediction"]
    assert pred["prior_only"] is None  # nic se nedopočítává


def test_result_does_not_show_prediction_of_another_run(api_db):
    client = TestClient(server_module.app)
    run_id, cutoff = _start_run(client, api_db)
    with sqlite3.connect(api_db) as conn:
        conn.execute("INSERT INTO runs(run_id, status, started_at) VALUES ('OTHER-RUN', 'RUNNING', '2026-10-10T10:00:00')")
    _insert_prediction(api_db, "OTHER-RUN", cutoff, {"prior_only": False})
    assert client.get(f"/api/analysis/{run_id}/result", headers=AUTH).json()["prediction"] is None


def test_statistics_engine_stores_factors(tmp_path, monkeypatch):
    monkeypatch.setenv("FAE_AUTO_HISTORY", "0")
    db_file = str(tmp_path / "engine_factors.db")
    initialize_database(db_file)
    cutoff = "2026-10-15T12:00:00+00:00"
    with sqlite3.connect(db_file) as conn:
        conn.execute("INSERT INTO teams(id, name, normalized_name) VALUES (1, 'A', 'a'), (2, 'B', 'b')")
        conn.execute("INSERT INTO matches(id, competition, home_team_id, away_team_id, scheduled_at) VALUES (1, 'Liga', 1, 2, '2026-10-15T18:00:00+00:00')")
        conn.execute("INSERT INTO runs(id, run_id, status, started_at) VALUES (1, 'R1', 'RUNNING', '2026-10-15T10:00:00')")

    StatisticalEngine(db_path=db_file).run_match_statistics(1, 1, 1, 2, cutoff)

    with sqlite3.connect(db_file) as conn:
        raw = conn.execute("SELECT factors_json FROM match_predictions WHERE run_id='R1'").fetchone()[0]
    factors = json.loads(raw)
    assert factors["prior_only"] is True
    assert "league_mean_goals" in factors


def test_legacy_match_predictions_table_gets_factors_column(tmp_path):
    db = tmp_path / "legacy_predictions.db"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE match_predictions (id INTEGER PRIMARY KEY AUTOINCREMENT, match_id INTEGER NOT NULL, run_id TEXT NOT NULL UNIQUE)")
    initialize_database(str(db))
    with sqlite3.connect(db) as conn:
        assert "factors_json" in {r[1] for r in conn.execute("PRAGMA table_info(match_predictions)")}
