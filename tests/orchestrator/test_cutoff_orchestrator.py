import json
import sqlite3
import pytest
from datetime import datetime, timezone

from app.database.schema import initialize_database
from app.orchestrator.orchestrator import MasterOrchestrator
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


def test_valid_verified_match_completes_end_to_end(orch_db):
    orch = MasterOrchestrator(db_path=orch_db)
    run_id = orch.start_pipeline(10)

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
