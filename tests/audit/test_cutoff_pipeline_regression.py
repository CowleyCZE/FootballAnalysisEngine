import json
import sqlite3
import pytest
from datetime import datetime, timezone
from fastapi.testclient import TestClient

from app.api.server import app, DB_PATH
from app.ai.context_builder import ContextBuilder
from app.workers.ai_worker import AIWorker
from app.audit.auditor import AdversarialAuditor
from app.orchestrator.orchestrator import MasterOrchestrator
from app.orchestrator.state_machine import MatchState
from app.jobs.models import JobStatus
from app.database.schema import initialize_database


@pytest.fixture
def audit_db(tmp_path, monkeypatch):
    db_file = str(tmp_path / "test_cutoff_audit.db")
    initialize_database(db_file)
    monkeypatch.setattr("app.api.server.DB_PATH", db_file)

    conn = sqlite3.connect(db_file)
    conn.execute("INSERT INTO teams(id, name, normalized_name) VALUES (1, 'Arsenal', 'arsenal'), (2, 'Chelsea', 'chelsea')")
    conn.execute("INSERT INTO competitions(id, name, country) VALUES (1, 'Premier League', 'England')")
    # Match 101 has scheduled_at
    conn.execute("INSERT INTO matches(id, competition, competition_id, home_team_id, away_team_id, scheduled_at, status) VALUES (101, 'Premier League', 1, 1, 2, '2026-10-20T20:00:00+00:00', 'RESOLVED')")
    # Match 102 has NULL scheduled_at
    conn.execute("INSERT INTO matches(id, competition, competition_id, home_team_id, away_team_id, scheduled_at, status) VALUES (102, 'Premier League', 1, 1, 2, NULL, 'RESOLVED')")
    conn.commit()
    conn.close()
    return db_file


def test_missing_cutoff_in_context_builder_and_ai_worker(audit_db):
    cb = ContextBuilder(db_path=audit_db)
    # Match 102 in DB has NULL scheduled_at and match_info has no cutoff
    context = cb.build_context(match_info={"match_id": 102}, run_db_id=1)
    assert context["match"]["data_cutoff_at"] is None

    res = AIWorker.execute({
        "match_id": 102,
        "db_path": audit_db,
        "claims": [{"claim_id": 1, "subject": "Arsenal", "predicate": "form", "object": "good"}],
        "match": {"match_id": 102}
    })
    assert res["status"] == "insufficient_data"


def test_invalid_cutoff_format_in_auditor(audit_db):
    auditor = AdversarialAuditor(db_path=audit_db)
    ai_analysis = {
        "status": "complete",
        "match": {"data_cutoff_at": "not-a-valid-date"}
    }
    result = auditor.audit(
        match_id=101,
        ai_run_id="ai-1",
        ai_analysis=ai_analysis,
        claims=[],
        statistics={},
        data_cutoff_at="not-a-valid-date"
    )
    assert result["status"] == "UNRESOLVED"
    has_missing_issue = any(i["type"] == "cutoff_missing" for i in result["issues"])
    assert has_missing_issue


def test_conflicting_cutoff_in_auditor(audit_db):
    auditor = AdversarialAuditor(db_path=audit_db)
    ai_analysis = {
        "status": "complete",
        "match": {"data_cutoff_at": "2026-10-20T20:00:00+00:00"}
    }
    result = auditor.audit(
        match_id=101,
        ai_run_id="ai-1",
        ai_analysis=ai_analysis,
        claims=[],
        statistics={},
        data_cutoff_at="2026-10-19T10:00:00+00:00"  # conflicting
    )
    assert result["status"] == "UNRESOLVED"
    has_conflict_issue = any(i["type"] == "cutoff_violation" for i in result["issues"])
    assert has_conflict_issue


def test_critical_cutoff_error_forces_unresolved_despite_high_audit_score(audit_db):
    auditor = AdversarialAuditor(db_path=audit_db)
    # Valid cutoff, but cutoff_missing is present or critical cutoff error
    ai_analysis = {
        "status": "complete",
        "match": {"data_cutoff_at": "invalid-cutoff-time"}
    }
    claims = [{
        "claim_id": 1,
        "evidence": [{
            "id": 999,
            "published_at": "2026-10-21T00:00:00+00:00"
        }]
    }]
    result = auditor.audit(
        match_id=101,
        ai_run_id="ai-1",
        ai_analysis=ai_analysis,
        claims=claims,
        statistics={},
        data_cutoff_at="invalid-cutoff-time"
    )
    assert result["status"] == "UNRESOLVED"


def test_api_result_rejection_when_unresolved_or_missing_cutoff(audit_db, monkeypatch):
    monkeypatch.setenv("WORKER_API_TOKEN", "test-secret")
    client = TestClient(app)
    headers = {"X-Worker-Token": "test-secret"}

    run_id = "RUN_UNRESOLVED_1"
    now_iso = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(audit_db) as conn:
        conn.execute("INSERT INTO runs(id, run_id, status, started_at) VALUES (10, ?, 'RUNNING', ?)", (run_id, now_iso))
        conn.execute("INSERT INTO pipeline_runs(run_id, match_id, state, cycle, max_cycles, started_at, updated_at) VALUES (?, 101, 'UNRESOLVED', 1, 3, ?, ?)", (run_id, now_iso, now_iso))
        conn.execute("INSERT INTO jobs(job_id, match_id, run_id, job_type, status, result_json) VALUES ('job-ai', 101, ?, 'AI_ANALYSIS', 'SUCCESS', ?)",
                     (run_id, json.dumps({"match_id": 101, "status": "complete", "conclusion": "Good match"})))

    resp = client.get(f"/api/analysis/{run_id}/result", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["state"] == "UNRESOLVED"
    # ai_analysis must be masked / status set to insufficient_data
    assert data["ai_analysis"]["status"] == "insufficient_data"


def test_finalizing_fails_when_required_job_failed(audit_db):
    master = MasterOrchestrator(db_path=audit_db)
    run_id = "RUN_FAIL_FINAL"
    now_iso = datetime.now(timezone.utc).isoformat()

    with sqlite3.connect(audit_db) as conn:
        conn.execute("INSERT INTO runs(id, run_id, status, started_at) VALUES (20, ?, 'RUNNING', ?)", (run_id, now_iso))
        conn.execute("INSERT INTO pipeline_runs(run_id, match_id, state, cycle, max_cycles, started_at, updated_at) VALUES (?, 101, 'FINALIZING', 1, 3, ?, ?)", (run_id, now_iso, now_iso))
        # Create a required research job that failed
        conn.execute("INSERT INTO research_tasks(run_id, run_db_id, match_id, task_uuid, domain, task_type, description, required, priority, capabilities_json, data_cutoff_at, home_team, away_team, competition, scheduled_at, status) VALUES (?, 20, 101, 'req-task-1', 'NEWS', 'FACT_COLLECTION', 'Desc', 1, 50, '[]', '2026-10-20T20:00:00+00:00', 'Arsenal', 'Chelsea', 'Premier League', '2026-10-20T20:00:00+00:00', 'FAILED')", (run_id,))
        conn.execute("INSERT INTO jobs(job_id, match_id, run_id, job_type, status, payload_json) VALUES ('job-req-1', 101, ?, 'RESEARCH', 'FAILED', ?)",
                     (run_id, json.dumps({"required": True})))

    master.tick(run_id)

    with sqlite3.connect(audit_db) as conn:
        row = conn.execute("SELECT state FROM pipeline_runs WHERE run_id = ?", (run_id,)).fetchone()
        assert row[0] == MatchState.UNRESOLVED
