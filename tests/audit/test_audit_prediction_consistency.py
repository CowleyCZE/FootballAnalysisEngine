"""TODO 1.2 – audit vidí predikci a hlídá, že jí AI text neodporuje (jen WARNING)."""
import json
import sqlite3

import pytest

from app.audit.auditor import AdversarialAuditor
from app.audit.consistency import ConsistencyChecker
from app.database.schema import initialize_database
from app.workers.audit_worker import AuditWorker

CUTOFF = "2026-10-20T20:00:00+00:00"
PREDICTION = {"predicted_score": "2-1", "predicted_home_goals": 2, "predicted_away_goals": 1}


def _types(issues):
    return [i["type"] for i in issues]


def test_contradicting_score_in_conclusion_is_warning():
    issues = ConsistencyChecker.check_statistical_consistency(
        {"prediction": PREDICTION}, [], {"conclusion": "Tip na výsledek zápasu je 0:3 pro hosty."}
    )
    found = [i for i in issues if i["type"] == "prediction_contradiction"]
    assert len(found) == 1
    assert found[0]["severity"] == "WARNING"
    assert found[0]["requires_research"] is False
    assert "2:1" in found[0]["description"]


def test_contradicting_score_in_key_factor_is_detected():
    analysis = {"conclusion": "Vyrovnaný zápas.", "key_factors": [{"factor": "Predikce: zápas skončí 1-1.", "evidence_ids": []}]}
    issues = ConsistencyChecker.check_prediction_consistency(PREDICTION, analysis)
    assert _types(issues) == ["prediction_contradiction"]


def test_matching_score_is_not_flagged_in_any_notation():
    for text in ("Tip modelu je 2:1.", "Predikce 2-1 pro domácí.", "Očekáváme výsledek 2–1."):
        assert ConsistencyChecker.check_prediction_consistency(PREDICTION, {"conclusion": text}) == []


def test_history_scores_and_times_are_not_flagged():
    analysis = {"conclusion": "Minule domácí vyhráli 3:0. Zápas začíná ve 20:00. Predikce vychází z formy."}
    assert ConsistencyChecker.check_prediction_consistency(PREDICTION, analysis) == []


def test_without_prediction_nothing_is_checked():
    analysis = {"conclusion": "Tip je 5:0."}
    assert ConsistencyChecker.check_statistical_consistency({}, [], analysis) == []


def test_auditor_reports_contradiction_without_breaking_audit(tmp_path):
    auditor = AdversarialAuditor(db_path=str(tmp_path / "audit.db"), log_dir=str(tmp_path / "logs"))
    result = auditor.audit(
        match_id=88, ai_run_id="ai-1",
        ai_analysis={"status": "complete", "key_factors": [], "conclusion": "Tip je 0:3."},
        claims=[], statistics={"prediction": PREDICTION}, data_cutoff_at=CUTOFF,
    )
    assert "prediction_contradiction" in _types(result["issues"])
    # WARNING nesnižuje skóre ani nespouští další výzkum.
    assert result["status"] == "AUDIT_COMPLETE"
    assert result["audit_score"] == 1.0
    assert result["research_jobs"] == []


@pytest.fixture
def audit_db(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # AuditWorker zapisuje logy do relativní složky logs/audit
    db_file = str(tmp_path / "audit_worker.db")
    initialize_database(db_file)
    with sqlite3.connect(db_file) as conn:
        conn.execute("INSERT INTO teams(id, name, normalized_name) VALUES (1, 'Arsenal', 'arsenal'), (2, 'Chelsea', 'chelsea')")
        conn.execute("INSERT INTO matches(id, competition, home_team_id, away_team_id, scheduled_at) VALUES (88, 'Premier League', 1, 2, '2026-10-20 20:00:00')")
        conn.execute("INSERT INTO runs(id, run_id, status, started_at) VALUES (1, 'RUN-88', 'RUNNING', '2026-10-20T10:00:00')")
        conn.execute(
            """INSERT INTO match_predictions(match_id, run_id, data_cutoff_at, model_version,
                   expected_home_goals, expected_away_goals, predicted_home_goals, predicted_away_goals,
                   home_win_probability, draw_probability, away_win_probability,
                   score_probabilities_json, sample_size)
               VALUES (88, 'RUN-88', ?, 'poisson-dc-context-v4', 1.7, 1.1, 2, 1, 0.5, 0.25, 0.25, ?, 10)""",
            (CUTOFF, json.dumps({"2-1": 0.15})),
        )
    return db_file


def _payload(db_file, conclusion, cutoff=CUTOFF):
    return {
        "match_id": 88, "run_db_id": 1, "db_path": db_file, "data_cutoff_at": cutoff,
        "ai_analysis": {"status": "complete", "key_factors": [], "conclusion": conclusion},
    }


def test_audit_worker_loads_prediction_from_db(audit_db):
    result = AuditWorker.execute(_payload(audit_db, "Tip modelu je 0:3 pro hosty."))
    assert "prediction_contradiction" in _types(result["issues"])


def test_audit_worker_consistent_text_has_no_contradiction(audit_db):
    result = AuditWorker.execute(_payload(audit_db, "Tip modelu je 2:1 pro domácí."))
    assert "prediction_contradiction" not in _types(result["issues"])
