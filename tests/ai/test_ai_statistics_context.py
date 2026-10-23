"""TODO 1.1 – AI kontext dostane výstup statistického modelu (predikci + snapshoty)."""
import json
import sqlite3

import pytest

from app.ai.context_builder import ContextBuilder
from app.database.schema import initialize_database
from app.workers.ai_worker import AIWorker

CUTOFF = "2026-10-20T20:00:00+00:00"
LATER = "2026-10-21T00:00:00+00:00"
SCORES = {"1-1": 0.12, "0-0": 0.08, "2-1": 0.15, "1-0": 0.11, "0-1": 0.05}


def _insert_prediction(conn, run_text, cutoff, home=2, away=1):
    conn.execute(
        """INSERT INTO match_predictions(match_id, run_id, data_cutoff_at, model_version,
               expected_home_goals, expected_away_goals, predicted_home_goals, predicted_away_goals,
               home_win_probability, draw_probability, away_win_probability,
               score_probabilities_json, sample_size)
           VALUES (88, ?, ?, 'poisson-dc-context-v4', 1.7, 1.1, ?, ?, 0.5, 0.25, 0.25, ?, 10)""",
        (run_text, cutoff, home, away, json.dumps(SCORES)),
    )


@pytest.fixture
def stats_db(tmp_path):
    db_file = str(tmp_path / "stats_context.db")
    initialize_database(db_file)
    conn = sqlite3.connect(db_file)
    conn.execute("INSERT INTO teams(id, name, normalized_name) VALUES (1, 'Arsenal', 'arsenal'), (2, 'Chelsea', 'chelsea')")
    conn.execute("INSERT INTO competitions(id, name, country) VALUES (1, 'Premier League', 'England')")
    conn.execute("INSERT INTO matches(id, competition, competition_id, home_team_id, away_team_id, scheduled_at) VALUES (88, 'Premier League', 1, 1, 2, '2026-10-20 20:00:00')")
    conn.execute("INSERT INTO runs(id, run_id, status, started_at) VALUES (1, 'RUN-88', 'RUNNING', '2026-10-20T10:00:00')")
    conn.execute("INSERT INTO runs(id, run_id, status, started_at) VALUES (2, 'RUN-88-B', 'RUNNING', '2026-10-20T11:00:00')")

    conn.execute("INSERT INTO claims(id, run_id, match_id, claim_text, claim_type, normalized_claim, status, confidence) VALUES (10, 1, 88, 'Arsenal striker is injured', 'injury', 'X:UNAVAILABLE', 'VALID', 0.95)")
    conn.execute("INSERT INTO sources(id, domain, name) VALUES (1, 'bbc.com', 'BBC Sport')")
    conn.execute("INSERT INTO documents(id, source_id, url, content_hash, retrieved_at) VALUES (1, 1, 'https://bbc.com/x', 'hash1', '2026-10-20T09:00:00')")
    conn.execute("INSERT INTO evidence(id, document_id, evidence_type, quoted_text, confidence) VALUES (100, 1, 'TEXT', 'Striker is ruled out', 0.95)")
    conn.execute("INSERT INTO claim_evidence(claim_id, evidence_id) VALUES (10, 100)")

    for team_id, pts in ((1, 9.0), (2, 4.0)):
        conn.execute(
            """INSERT INTO statistical_snapshots(run_id, match_id, team_id, metric, value, sample_size,
                   coverage, data_cutoff_at, calculation_version)
               VALUES (1, 88, ?, 'form_points', ?, 5, 0.0, ?, '1.0.0')""",
            (team_id, pts, CUTOFF),
        )
    conn.commit()
    conn.close()
    return db_file


def test_context_contains_prediction_and_snapshots(stats_db):
    with sqlite3.connect(stats_db) as conn:
        _insert_prediction(conn, "RUN-88", CUTOFF)

    context = ContextBuilder(db_path=stats_db).build_context(
        match_info={"match_id": 88, "data_cutoff_at": CUTOFF}, run_db_id=1
    )

    pred = context["statistics"]["prediction"]
    assert pred["predicted_score"] == "2-1"
    assert pred["model_version"] == "poisson-dc-context-v4"
    assert pred["expected_goals"] == {"home": 1.7, "away": 1.1}
    assert pred["probabilities_1x2"] == {"home_win": 0.5, "draw": 0.25, "away_win": 0.25}
    assert pred["sample_size"] == 10
    # top-3 seřazené podle pravděpodobnosti
    assert list(pred["top_scores"]) == ["2-1", "1-1", "1-0"]

    snaps = {(s["team"], s["metric"]): s for s in context["statistics"]["snapshots"]}
    assert snaps[("home", "form_points")]["value"] == 9.0
    assert snaps[("away", "form_points")]["value"] == 4.0


def test_prediction_present_does_not_lower_data_quality(stats_db):
    with sqlite3.connect(stats_db) as conn:
        _insert_prediction(conn, "RUN-88", CUTOFF)
    builder = ContextBuilder(db_path=stats_db)

    with_pred = builder.build_context(match_info={"match_id": 88, "data_cutoff_at": CUTOFF}, run_db_id=1)
    assert "statistics" not in with_pred["data_quality"]["missing_data"]
    assert with_pred["data_quality"]["score"] == 1.0

    # Bez predikce (jiný běh mimo cutoff) se kvalita snižuje a statistika chybí.
    with sqlite3.connect(stats_db) as conn:
        conn.execute("DELETE FROM match_predictions")
        conn.execute("DELETE FROM statistical_snapshots")
    without = builder.build_context(match_info={"match_id": 88, "data_cutoff_at": CUTOFF}, run_db_id=1)
    assert "statistics" in without["data_quality"]["missing_data"]
    assert without["data_quality"]["score"] < with_pred["data_quality"]["score"]


def test_prediction_after_cutoff_is_never_used(stats_db):
    with sqlite3.connect(stats_db) as conn:
        _insert_prediction(conn, "RUN-88-B", LATER, home=4, away=0)

    context = ContextBuilder(db_path=stats_db).build_context(
        match_info={"match_id": 88, "data_cutoff_at": CUTOFF}, run_db_id=2
    )
    assert "prediction" not in context["statistics"]


def test_falls_back_to_newest_prediction_not_after_cutoff(stats_db):
    with sqlite3.connect(stats_db) as conn:
        _insert_prediction(conn, "RUN-88", CUTOFF, home=2, away=1)
        _insert_prediction(conn, "RUN-88-B", LATER, home=4, away=0)

    # Běh 2 nemá použitelnou predikci (je po cutoffu) -> platná z běhu 1, nikdy pozdější.
    context = ContextBuilder(db_path=stats_db).build_context(
        match_info={"match_id": 88, "data_cutoff_at": CUTOFF}, run_db_id=2
    )
    assert context["statistics"]["prediction"]["run_id"] == "RUN-88"
    assert context["statistics"]["prediction"]["predicted_score"] == "2-1"


def test_explicit_statistics_are_not_overridden_by_database(stats_db):
    with sqlite3.connect(stats_db) as conn:
        _insert_prediction(conn, "RUN-88", CUTOFF)

    context = ContextBuilder(db_path=stats_db).build_context(
        match_info={"match_id": 88, "data_cutoff_at": CUTOFF}, statistics={}, run_db_id=1
    )
    assert context["statistics"] == {}


def test_ai_prompt_contains_prediction_and_forbids_changing_it(stats_db, monkeypatch):
    with sqlite3.connect(stats_db) as conn:
        _insert_prediction(conn, "RUN-88", CUTOFF)

    captured = {}

    class CapturingOllama:
        def __init__(self, *args, **kwargs):
            pass

        def generate(self, prompt, require_json=True):
            captured["prompt"] = prompt
            raise RuntimeError("stop after capturing prompt")

    monkeypatch.setattr("app.workers.ai_worker.OllamaClient", CapturingOllama)

    AIWorker.execute({"match_id": 88, "run_db_id": 1, "db_path": stats_db, "data_cutoff_at": CUTOFF})

    prompt = captured["prompt"]
    # Kontext se do promptu serializuje kompaktně (bez mezer), nezávisle na formátu JSON.
    assert '"predicted_score":"2-1"' in prompt.replace('": "', '":"')
    assert "MUST NOT change" in prompt
