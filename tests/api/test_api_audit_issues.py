"""TODO 1.4 – audit_issues v API nejsou prázdné (audit_runs.run_id = pipeline run_id)."""
import sqlite3

import pytest
from fastapi.testclient import TestClient

import app.api.server as server_module
from app.audit.auditor import AdversarialAuditor
from app.database.schema import initialize_database
from app.workers.audit_worker import AuditWorker

AUTH = {"X-Worker-Token": "test-secret-token"}
CUTOFF = "2026-10-15T12:00:00+00:00"


@pytest.fixture
def api_db(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # logs/audit se zapisují do relativní složky
    db_file = str(tmp_path / "api_audit.db")
    monkeypatch.setattr(server_module, "DB_PATH", db_file)
    monkeypatch.setenv("WORKER_API_TOKEN", "test-secret-token")
    initialize_database(db_file)
    with sqlite3.connect(db_file) as conn:
        conn.execute("INSERT INTO teams(id, name, normalized_name) VALUES (1, 'Real Madrid', 'real_madrid'), (2, 'Barcelona', 'barcelona')")
        conn.execute("INSERT INTO competitions(id, name, country) VALUES (1, 'La Liga', 'Spain')")
        conn.execute("INSERT INTO matches(id, competition, competition_id, home_team_id, away_team_id, scheduled_at, status) VALUES (101, 'La Liga', 1, 1, 2, '2026-10-15T18:00:00+00:00', 'RESOLVED')")
    return db_file


def _audit_payload(db_file, run_id):
    return {
        "match_id": 101, "run_id": run_id, "db_path": db_file, "data_cutoff_at": CUTOFF,
        "ai_analysis": {"status": "insufficient_data", "data_quality": {"missing_data": ["Ollama offline"]}, "key_factors": []},
    }


def test_api_returns_audit_issues_after_audit(api_db):
    client = TestClient(server_module.app)
    run_id = client.post("/api/analysis/start", json={"match_id": 101}, headers=AUTH).json()["run_id"]

    result = AuditWorker.execute(_audit_payload(api_db, run_id))
    assert any(i["type"] == "ai_analysis_unavailable" for i in result["issues"])
    assert result["pipeline_run_id"] == run_id

    issues = client.get(f"/api/analysis/{run_id}/result", headers=AUTH).json()["audit_issues"]
    assert any(i["issue_type"] == "ai_analysis_unavailable" and i["severity"] == "WARNING" for i in issues)


def test_api_audit_issues_come_from_latest_audit_of_that_run_only(api_db):
    client = TestClient(server_module.app)
    run_id = client.post("/api/analysis/start", json={"match_id": 101}, headers=AUTH).json()["run_id"]
    other_run = client.post("/api/analysis/start", json={"match_id": 101}, headers=AUTH).json()["run_id"]

    AuditWorker.execute(_audit_payload(api_db, other_run))
    assert client.get(f"/api/analysis/{run_id}/result", headers=AUTH).json()["audit_issues"] == []


def test_audit_runs_keeps_audit_id_separate_from_pipeline_run_id(tmp_path):
    db_file = str(tmp_path / "audit.db")
    auditor = AdversarialAuditor(db_path=db_file, log_dir=str(tmp_path / "logs"))
    result = auditor.audit(
        match_id=1, ai_run_id="ai", ai_analysis={"status": "complete", "key_factors": []},
        claims=[], statistics={}, data_cutoff_at=CUTOFF, pipeline_run_id="PIPE-1",
    )
    with sqlite3.connect(db_file) as conn:
        audit_id, run_id = conn.execute("SELECT audit_id, run_id FROM audit_runs").fetchone()
    assert run_id == "PIPE-1"
    assert audit_id == result["run_id"]
