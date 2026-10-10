import json
import sqlite3
import pytest
from datetime import datetime, timezone

from app.database.schema import initialize_database
from app.orchestrator.orchestrator import MasterOrchestrator
from app.orchestrator.match_resolver import MatchResolver
from app.orchestrator.models import AnalysisRequest
from app.orchestrator.state_machine import MatchState
from app.jobs.models import JobStatus, JobPriority


@pytest.fixture
def orch_db(tmp_path):
    db_file = str(tmp_path / "test_orch_cutoff.db")
    initialize_database(db_file)
    with sqlite3.connect(db_file) as conn:
        conn.execute("INSERT INTO teams(id, name, normalized_name) VALUES (1, 'Arsenal', 'arsenal')")
        conn.execute("INSERT INTO teams(id, name, normalized_name) VALUES (2, 'Chelsea', 'chelsea')")
        conn.execute(
            "INSERT INTO matches(id, competition, home_team_id, away_team_id, scheduled_at, status) VALUES (10, 'Premier League', 1, 2, '2026-10-04T15:00:00Z', 'RESOLVED')"
        )
    return db_file


def test_match_resolver_missing_cutoff_is_none(orch_db):
    resolver = MatchResolver(db_path=orch_db)
    req = AnalysisRequest(
        home_team="Arsenal",
        away_team="Chelsea",
        competition="Premier League",
        scheduled_at=datetime(2026, 10, 4, 15, 0, tzinfo=timezone.utc),
        data_cutoff_at=None,
    )
    identity = resolver.resolve(req)
    assert identity.scheduled_at == datetime(2026, 10, 4, 15, 0, tzinfo=timezone.utc)
    assert identity.data_cutoff_at is None


def test_match_resolver_explicit_cutoff_preserved(orch_db):
    resolver = MatchResolver(db_path=orch_db)
    cutoff = datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc)
    req = AnalysisRequest(
        home_team="Arsenal",
        away_team="Chelsea",
        competition="Premier League",
        scheduled_at=datetime(2026, 10, 4, 15, 0, tzinfo=timezone.utc),
        data_cutoff_at=cutoff,
    )
    identity = resolver.resolve(req)
    assert identity.scheduled_at == datetime(2026, 10, 4, 15, 0, tzinfo=timezone.utc)
    assert identity.data_cutoff_at == cutoff


def test_master_orchestrator_get_match_identity_missing_cutoff(orch_db):
    orch = MasterOrchestrator(db_path=orch_db)
    identity = orch._get_match_identity_from_id(10)
    assert identity is not None
    assert identity.scheduled_at == datetime(2026, 10, 4, 15, 0, tzinfo=timezone.utc)
    assert identity.data_cutoff_at is None


def test_master_orchestrator_get_match_identity_explicit_cutoff(orch_db):
    orch = MasterOrchestrator(db_path=orch_db)
    cutoff = datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc)
    identity = orch._get_match_identity_from_id(10, data_cutoff_at=cutoff)
    assert identity is not None
    assert identity.scheduled_at == datetime(2026, 10, 4, 15, 0, tzinfo=timezone.utc)
    assert identity.data_cutoff_at == cutoff


def test_research_tasks_and_job_payloads_preserve_missing_cutoff(orch_db):
    orch = MasterOrchestrator(db_path=orch_db)
    run_id = orch.start_pipeline(10, data_cutoff_at=None)

    with sqlite3.connect(orch_db) as conn:
        conn.row_factory = sqlite3.Row
        task = conn.execute("SELECT data_cutoff_at FROM research_tasks WHERE run_id = ?", (run_id,)).fetchone()
        job = conn.execute("SELECT payload_json FROM jobs WHERE run_id = ?", (run_id,)).fetchone()

    assert task["data_cutoff_at"] is None
    payload = json.loads(job["payload_json"])
    assert payload.get("data_cutoff_at") is None
    assert payload.get("cutoff_datetime") is None
    assert payload.get("cutoff") is None


def test_missing_cutoff_cannot_lead_to_completed(orch_db):
    orch = MasterOrchestrator(db_path=orch_db)
    run_id = orch.start_pipeline(10)

    with sqlite3.connect(orch_db) as conn:
        conn.execute("UPDATE pipeline_runs SET state = 'AUDITING' WHERE run_id = ?", (run_id,))

        # Insert audit job result indicating missing cutoff
        audit_res = {
            "status": "UNRESOLVED",
            "audit_score": 0.7,
            "issues": [
                {
                    "type": "cutoff_missing",
                    "severity": "CRITICAL",
                    "description": "Není k dispozici žádný platný data_cutoff_at pro audit.",
                }
            ],
        }
        conn.execute(
            "INSERT INTO jobs(job_id, job_type, match_id, run_id, status, result_json, priority) VALUES (?, 'AUDIT', 10, ?, 'SUCCESS', ?, 100)",
            ("JOB-AUDIT-1", run_id, json.dumps(audit_res)),
        )

    orch.tick(run_id)

    with sqlite3.connect(orch_db) as conn:
        state = conn.execute("SELECT state FROM pipeline_runs WHERE run_id = ?", (run_id,)).fetchone()[0]

    assert state == MatchState.UNRESOLVED
    assert state != MatchState.COMPLETED


def test_invalid_cutoff_cannot_lead_to_completed(orch_db):
    orch = MasterOrchestrator(db_path=orch_db)
    run_id = orch.start_pipeline(10)

    with sqlite3.connect(orch_db) as conn:
        conn.execute("UPDATE pipeline_runs SET state = 'AUDITING' WHERE run_id = ?", (run_id,))
        audit_res = {
            "status": "AUDIT_COMPLETE",
            "audit_score": 0.8,
            "issues": [
                {
                    "type": "cutoff_violation",
                    "severity": "CRITICAL",
                    "description": "Evidence exceeds cutoff",
                }
            ],
        }
        conn.execute(
            "INSERT INTO jobs(job_id, job_type, match_id, run_id, status, result_json, priority) VALUES (?, 'AUDIT', 10, ?, 'SUCCESS', ?, 100)",
            ("JOB-AUDIT-2", run_id, json.dumps(audit_res)),
        )

    orch.tick(run_id)

    with sqlite3.connect(orch_db) as conn:
        state = conn.execute("SELECT state FROM pipeline_runs WHERE run_id = ?", (run_id,)).fetchone()[0]

    assert state == MatchState.UNRESOLVED
    assert state != MatchState.COMPLETED


def test_auditor_response_with_critical_cutoff_rejected_despite_high_score(orch_db):
    orch = MasterOrchestrator(db_path=orch_db)
    run_id = orch.start_pipeline(10)

    with sqlite3.connect(orch_db) as conn:
        conn.execute("UPDATE pipeline_runs SET state = 'AUDITING' WHERE run_id = ?", (run_id,))
        # Audit result claims status is AUDIT_COMPLETE and score is 0.95, but has a critical cutoff issue
        audit_res = {
            "status": "AUDIT_COMPLETE",
            "audit_score": 0.95,
            "issues": [
                {
                    "type": "cutoff_missing",
                    "severity": "CRITICAL",
                    "description": "Cutoff timestamp missing",
                }
            ],
        }
        conn.execute(
            "INSERT INTO jobs(job_id, job_type, match_id, run_id, status, result_json, priority) VALUES (?, 'AUDIT', 10, ?, 'SUCCESS', ?, 100)",
            ("JOB-AUDIT-3", run_id, json.dumps(audit_res)),
        )

    orch.tick(run_id)

    with sqlite3.connect(orch_db) as conn:
        state = conn.execute("SELECT state FROM pipeline_runs WHERE run_id = ?", (run_id,)).fetchone()[0]

    assert state == MatchState.UNRESOLVED


def test_research_worker_cutoff_failure_propagates_to_pipeline_unresolved(orch_db):
    orch = MasterOrchestrator(db_path=orch_db)
    run_id = orch.start_pipeline(10)

    # Mark research tasks/jobs as FAILED due to cutoff error
    with sqlite3.connect(orch_db) as conn:
        conn.execute("UPDATE jobs SET status = 'FAILED', result_json = ? WHERE run_id = ?", (json.dumps({"status": "FAILED", "error": "Match context resolution failed"}), run_id))
        conn.execute("UPDATE research_tasks SET status = 'FAILED' WHERE run_id = ?", (run_id,))

    orch.tick(run_id)

    with sqlite3.connect(orch_db) as conn:
        state = conn.execute("SELECT state FROM pipeline_runs WHERE run_id = ?", (run_id,)).fetchone()[0]

    assert state == MatchState.UNRESOLVED


def test_insufficient_data_remains_unresolved(orch_db):
    orch = MasterOrchestrator(db_path=orch_db)
    run_id = orch.start_pipeline(10)

    with sqlite3.connect(orch_db) as conn:
        conn.execute("UPDATE pipeline_runs SET state = 'AUDITING' WHERE run_id = ?", (run_id,))
        audit_res = {
            "status": "UNRESOLVED",
            "audit_score": 0.0,
            "issues": [
                {
                    "type": "ai_analysis_unavailable",
                    "severity": "CRITICAL",
                    "description": "insufficient_data",
                }
            ],
        }
        conn.execute(
            "INSERT INTO jobs(job_id, job_type, match_id, run_id, status, result_json, priority) VALUES (?, 'AUDIT', 10, ?, 'SUCCESS', ?, 100)",
            ("JOB-AUDIT-4", run_id, json.dumps(audit_res)),
        )

    orch.tick(run_id)

    with sqlite3.connect(orch_db) as conn:
        state = conn.execute("SELECT state FROM pipeline_runs WHERE run_id = ?", (run_id,)).fetchone()[0]

    assert state == MatchState.UNRESOLVED


def test_concurrent_runs_same_match_different_cutoffs(orch_db):
    orch = MasterOrchestrator(db_path=orch_db)
    cutoff1 = datetime(2026, 10, 2, 10, 0, tzinfo=timezone.utc)
    cutoff2 = datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc)

    run_id1 = orch.start_pipeline(10, data_cutoff_at=cutoff1)
    run_id2 = orch.start_pipeline(10, data_cutoff_at=cutoff2)

    assert run_id1 != run_id2

    # Mark all initial jobs as SUCCESS and set state to CALCULATING for both
    with sqlite3.connect(orch_db) as conn:
        conn.execute("UPDATE jobs SET status = 'SUCCESS' WHERE run_id IN (?, ?)", (run_id1, run_id2))
        conn.execute("UPDATE pipeline_runs SET state = 'CALCULATING' WHERE run_id IN (?, ?)", (run_id1, run_id2))

    orch.tick(run_id1)
    orch.tick(run_id2)

    with sqlite3.connect(orch_db) as conn:
        conn.row_factory = sqlite3.Row
        ai_job1 = conn.execute("SELECT payload_json FROM jobs WHERE run_id = ? AND job_type = 'AI_ANALYSIS'", (run_id1,)).fetchone()
        ai_job2 = conn.execute("SELECT payload_json FROM jobs WHERE run_id = ? AND job_type = 'AI_ANALYSIS'", (run_id2,)).fetchone()

    payload1 = json.loads(ai_job1["payload_json"])
    payload2 = json.loads(ai_job2["payload_json"])

    assert payload1["data_cutoff_at"] == cutoff1.isoformat()
    assert payload2["data_cutoff_at"] == cutoff2.isoformat()


def test_missing_cutoff_transition_to_unresolved_despite_audit_complete(orch_db):
    orch = MasterOrchestrator(db_path=orch_db)
    run_id = orch.start_pipeline(10, data_cutoff_at=None)

    with sqlite3.connect(orch_db) as conn:
        conn.execute("UPDATE pipeline_runs SET state = 'AUDITING' WHERE run_id = ?", (run_id,))
        audit_res = {"status": "AUDIT_COMPLETE", "audit_score": 1.0, "issues": []}
        conn.execute(
            "INSERT INTO jobs(job_id, job_type, match_id, run_id, status, result_json, priority) VALUES ('JOB-AUDIT-NONE', 'AUDIT', 10, ?, 'SUCCESS', ?, 100)",
            (run_id, json.dumps(audit_res)),
        )

    orch.tick(run_id)

    with sqlite3.connect(orch_db) as conn:
        state = conn.execute("SELECT state FROM pipeline_runs WHERE run_id = ?", (run_id,)).fetchone()[0]

    assert state == MatchState.UNRESOLVED


def test_reanalysis_payload_contains_cutoff_and_match(orch_db):
    orch = MasterOrchestrator(db_path=orch_db)
    cutoff = datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc)
    run_id = orch.start_pipeline(10, data_cutoff_at=cutoff)

    # Set state to RESEARCHING and insert a finished research job
    with sqlite3.connect(orch_db) as conn:
        conn.execute("UPDATE pipeline_runs SET state = 'RESEARCHING' WHERE run_id = ?", (run_id,))
        conn.execute(
            "INSERT INTO jobs(job_id, job_type, match_id, run_id, status, priority) VALUES ('J-RES-1', 'RESEARCH', 10, ?, 'SUCCESS', 50)",
            (run_id,)
        )

    orch.tick(run_id)

    with sqlite3.connect(orch_db) as conn:
        conn.row_factory = sqlite3.Row
        job = conn.execute(
            "SELECT payload_json FROM jobs WHERE run_id = ? AND job_type = 'AI_ANALYSIS' AND payload_json LIKE '%re_analysis%'",
            (run_id,)
        ).fetchone()

    assert job is not None
    payload = json.loads(job["payload_json"])
    assert payload.get("data_cutoff_at") == cutoff.isoformat()
    assert payload.get("cutoff_datetime") == cutoff.isoformat()
    assert payload.get("cutoff") == cutoff.isoformat()
    assert payload.get("match") is not None
    assert payload["match"].get("data_cutoff_at") == cutoff.isoformat()
    assert payload["match"].get("home_team") == "Arsenal"
    assert payload["match"].get("away_team") == "Chelsea"


def test_reanalysis_cutoff_preserved_new_orchestrator_instance(orch_db):
    cutoff = datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc)
    orch1 = MasterOrchestrator(db_path=orch_db)
    run_id = orch1.start_pipeline(10, data_cutoff_at=cutoff)

    # Set state to RESEARCHING and insert a finished research job
    with sqlite3.connect(orch_db) as conn:
        conn.execute("UPDATE pipeline_runs SET state = 'RESEARCHING' WHERE run_id = ?", (run_id,))
        conn.execute(
            "INSERT INTO jobs(job_id, job_type, match_id, run_id, status, priority) VALUES ('J-RES-NEW-INST', 'RESEARCH', 10, ?, 'SUCCESS', 50)",
            (run_id,)
        )

    # Create new instance of MasterOrchestrator over same DB
    orch2 = MasterOrchestrator(db_path=orch_db)
    orch2.tick(run_id)

    with sqlite3.connect(orch_db) as conn:
        conn.row_factory = sqlite3.Row
        job = conn.execute(
            "SELECT payload_json FROM jobs WHERE run_id = ? AND job_type = 'AI_ANALYSIS' AND payload_json LIKE '%re_analysis%'",
            (run_id,)
        ).fetchone()

    assert job is not None
    payload = json.loads(job["payload_json"])
    assert payload.get("data_cutoff_at") == cutoff.isoformat()
    assert payload["match"].get("data_cutoff_at") == cutoff.isoformat()


def test_concurrent_reanalysis_distinct_cutoffs(orch_db):
    orch = MasterOrchestrator(db_path=orch_db)
    cutoff1 = datetime(2026, 10, 2, 10, 0, tzinfo=timezone.utc)
    cutoff2 = datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc)

    run_id1 = orch.start_pipeline(10, data_cutoff_at=cutoff1)
    run_id2 = orch.start_pipeline(10, data_cutoff_at=cutoff2)

    with sqlite3.connect(orch_db) as conn:
        conn.execute("UPDATE pipeline_runs SET state = 'RESEARCHING' WHERE run_id IN (?, ?)", (run_id1, run_id2))
        conn.execute("INSERT INTO jobs(job_id, job_type, match_id, run_id, status, priority) VALUES ('J-R1', 'RESEARCH', 10, ?, 'SUCCESS', 50)", (run_id1,))
        conn.execute("INSERT INTO jobs(job_id, job_type, match_id, run_id, status, priority) VALUES ('J-R2', 'RESEARCH', 10, ?, 'SUCCESS', 50)", (run_id2,))

    orch.tick(run_id1)
    orch.tick(run_id2)

    with sqlite3.connect(orch_db) as conn:
        conn.row_factory = sqlite3.Row
        job1 = conn.execute("SELECT payload_json FROM jobs WHERE run_id = ? AND job_type = 'AI_ANALYSIS' AND payload_json LIKE '%re_analysis%'", (run_id1,)).fetchone()
        job2 = conn.execute("SELECT payload_json FROM jobs WHERE run_id = ? AND job_type = 'AI_ANALYSIS' AND payload_json LIKE '%re_analysis%'", (run_id2,)).fetchone()

    payload1 = json.loads(job1["payload_json"])
    payload2 = json.loads(job2["payload_json"])

    assert payload1.get("data_cutoff_at") == cutoff1.isoformat()
    assert payload2.get("data_cutoff_at") == cutoff2.isoformat()
    assert payload1["match"].get("data_cutoff_at") == cutoff1.isoformat()
    assert payload2["match"].get("data_cutoff_at") == cutoff2.isoformat()


def test_valid_verified_match_completes_end_to_end(orch_db):
    orch = MasterOrchestrator(db_path=orch_db)
    cutoff = datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc)
    run_id = orch.start_pipeline(10, data_cutoff_at=cutoff)

    # 1. Complete research tasks
    with sqlite3.connect(orch_db) as conn:
        conn.execute("UPDATE jobs SET status = 'SUCCESS', result_json = '{\"status\": \"SUCCESS\"}' WHERE run_id = ?", (run_id,))
        conn.execute("UPDATE research_tasks SET status = 'SUCCESS' WHERE run_id = ?", (run_id,))

    for _ in range(5):
        orch.tick(run_id)

    # 2. Complete AI analysis job
    with sqlite3.connect(orch_db) as conn:
        conn.execute(
            "UPDATE jobs SET status = 'SUCCESS', result_json = ? WHERE run_id = ? AND job_type = 'AI_ANALYSIS'",
            (json.dumps({"status": "complete", "key_factors": []}), run_id),
        )

    orch.tick(run_id)  # ANALYZING -> AUDITING -> creates AUDIT job

    # 3. Complete AUDIT job with valid status
    with sqlite3.connect(orch_db) as conn:
        audit_res = {
            "status": "AUDIT_COMPLETE",
            "audit_score": 1.0,
            "issues": [],
        }
        conn.execute(
            "UPDATE jobs SET status = 'SUCCESS', result_json = ? WHERE run_id = ? AND job_type = 'AUDIT'",
            (json.dumps(audit_res), run_id),
        )

    orch.tick(run_id)  # AUDITING -> FINALIZING
    orch.tick(run_id)  # FINALIZING -> COMPLETED

    with sqlite3.connect(orch_db) as conn:
        state = conn.execute("SELECT state FROM pipeline_runs WHERE run_id = ?", (run_id,)).fetchone()[0]

    assert state in (MatchState.FINALIZING, MatchState.COMPLETED)
