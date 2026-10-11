import json
import sqlite3
import pytest
from datetime import datetime, timezone

from app.database.schema import initialize_database
from app.orchestrator.orchestrator import MasterOrchestrator
from app.orchestrator.state_machine import MatchState
from app.workers.research_worker import ResearchWorker
from app.research.engine import ResearchEngine
from app.database.research_repository import ResearchRepository


@pytest.fixture
def fix_db(tmp_path):
    db_file = str(tmp_path / "acceptance_fixes.db")
    initialize_database(db_file)
    with sqlite3.connect(db_file) as conn:
        conn.execute("INSERT INTO teams (id, name, normalized_name) VALUES (1, 'Arsenal', 'arsenal')")
        conn.execute("INSERT INTO teams (id, name, normalized_name) VALUES (2, 'Chelsea', 'chelsea')")
        conn.execute("INSERT INTO competitions (id, name) VALUES (1, 'Premier League')")
        conn.execute(
            "INSERT INTO matches (id, home_team_id, away_team_id, competition, scheduled_at, status) "
            "VALUES (10, 1, 2, 'Premier League', '2026-10-04T15:00:00+00:00', 'RESOLVED')"
        )
        conn.commit()
    return db_file


def test_runs_status_and_finished_at_synchronized(fix_db):
    orc = MasterOrchestrator(db_path=fix_db)
    run_id = orc.start_pipeline(10, data_cutoff_at=datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc))

    with sqlite3.connect(fix_db) as conn:
        run_st = conn.execute("SELECT status, finished_at FROM runs WHERE run_id=?", (run_id,)).fetchone()
        prun_st = conn.execute("SELECT state, finished_at FROM pipeline_runs WHERE run_id=?", (run_id,)).fetchone()

    assert run_st[0] in ("RUNNING", "DISCOVERY")
    assert run_st[1] is None
    assert prun_st[0] == "DISCOVERY"

    orc.state_machine.transition_to(run_id, MatchState.UNRESOLVED, "Test unresolved transition")

    with sqlite3.connect(fix_db) as conn:
        run_st = conn.execute("SELECT status, finished_at FROM runs WHERE run_id=?", (run_id,)).fetchone()
        prun_st = conn.execute("SELECT state, finished_at, error_text FROM pipeline_runs WHERE run_id=?", (run_id,)).fetchone()

    assert run_st[0] == "UNRESOLVED"
    assert run_st[1] is not None
    assert prun_st[0] == "UNRESOLVED"
    assert prun_st[1] is not None
    assert prun_st[2] == "Test unresolved transition"


def test_searxng_unavailable_saves_queries_and_pipeline_unresolved(fix_db):
    orc = MasterOrchestrator(db_path=fix_db)
    run_id = orc.start_pipeline(10, data_cutoff_at=datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc))

    with sqlite3.connect(fix_db) as conn:
        conn.row_factory = sqlite3.Row
        job_row = conn.execute("SELECT job_id, payload_json FROM jobs WHERE run_id=? AND job_type='RESEARCH'", (run_id,)).fetchone()

    payload = json.loads(job_row["payload_json"])
    task_id = payload["task_id"]

    class FailingSearchAdapter:
        def search(self, *args, **kwargs):
            raise ConnectionError("SearXNG service unavailable (ConnectionRefusedError)")

    worker = ResearchWorker(db_path=fix_db)
    worker.engine = ResearchEngine(repository=worker.repository, search_adapter=FailingSearchAdapter())

    res = worker.run_execute(payload)
    assert res["status"] == "FAILED"
    assert "SearXNG service unavailable" in res["error"]

    with sqlite3.connect(fix_db) as conn:
        queries = conn.execute(
            "SELECT query, result_count FROM research_queries WHERE session_id IN (SELECT id FROM research_sessions WHERE task_id=?)",
            (task_id,),
        ).fetchall()
        assert len(queries) > 0
        assert all(q[1] == 0 for q in queries)


def test_terminal_task_retry_does_not_crash_with_already_terminal(fix_db):
    with sqlite3.connect(fix_db) as conn:
        conn.execute("INSERT INTO runs(id, run_id, status, started_at) VALUES (100, 'RUN-T1', 'RUNNING', '2026-10-04T10:00:00Z')")
        conn.execute("""INSERT INTO research_tasks(
            id, run_id, run_db_id, match_id, task_uuid, domain, task_type, description,
            required, priority, capabilities_json, data_cutoff_at, home_team, away_team,
            competition, scheduled_at, status, attempt_number
        ) VALUES (1, 'RUN-T1', 100, 10, 'TASK-T1', 'ABSENCES_HOME', 'NEWS_COLLECTION', 'test',
                  1, 90, '["RESEARCH"]', '2026-10-04T12:00:00Z', 'Arsenal', 'Chelsea',
                  'Premier League', '2026-10-04T15:00:00Z', 'QUEUED', 1)""")

    repo = ResearchRepository(db_path=fix_db)
    repo.mark_task_running(1, 1)
    exec_id = repo.create_execution("EXEC-1", 1, 1)
    repo.complete_execution(exec_id, "FAILED", "Initial network error")

    with sqlite3.connect(fix_db) as conn:
        task_st = conn.execute("SELECT status FROM research_tasks WHERE id=1").fetchone()[0]
    assert task_st == "FAILED"

    # Attempt 2 retry should reset task status to RUNNING without raising RuntimeError
    repo.mark_task_running(1, 2)
    with sqlite3.connect(fix_db) as conn:
        task_st = conn.execute("SELECT status, attempt_number FROM research_tasks WHERE id=1").fetchone()
    assert task_st[0] == "RUNNING"
    assert task_st[1] == 2


def test_nested_zero_sample_size_in_statistics_blocks_ai_analysis(fix_db):
    orc = MasterOrchestrator(db_path=fix_db)
    run_id = orc.start_pipeline(10, data_cutoff_at=datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc))

    nested_stats_result = {
        "status": "COMPLETED",
        "sample_size": 10,
        "form": {
            "status": "INSUFFICIENT_DATA",
            "sample_size": 0,
        },
        "formula": {
            "sample_size": 0,
        },
        "warnings": ["Insufficient historical matches for away team"],
    }

    with sqlite3.connect(fix_db) as conn:
        conn.execute(
            "UPDATE jobs SET status='SUCCESS', result_json=? WHERE run_id=? AND job_type='STATISTICS'",
            (json.dumps(nested_stats_result), run_id),
        )
        conn.execute("UPDATE pipeline_runs SET state='CALCULATING' WHERE run_id=?", (run_id,))

    orc.tick(run_id)

    with sqlite3.connect(fix_db) as conn:
        state = conn.execute("SELECT state FROM pipeline_runs WHERE run_id=?", (run_id,)).fetchone()[0]
        ai_jobs = conn.execute("SELECT COUNT(*) FROM jobs WHERE run_id=? AND job_type='AI_ANALYSIS'", (run_id,)).fetchone()[0]

    assert state == MatchState.UNRESOLVED
    assert ai_jobs == 0


def test_sufficient_statistics_allows_ai_analysis_and_audit_creation(fix_db):
    orc = MasterOrchestrator(db_path=fix_db)
    run_id = orc.start_pipeline(10, data_cutoff_at=datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc))

    valid_stats = {
        "status": "COMPLETED",
        "sample_size": 10,
        "coverage": 1.0,
        "form": {
            "status": "OK",
            "sample_size": 10,
        },
    }

    with sqlite3.connect(fix_db) as conn:
        conn.execute(
            "UPDATE jobs SET status='SUCCESS', result_json=? WHERE run_id=? AND job_type='STATISTICS'",
            (json.dumps(valid_stats), run_id),
        )
        conn.execute("UPDATE pipeline_runs SET state='CALCULATING' WHERE run_id=?", (run_id,))

    orc.tick(run_id)

    with sqlite3.connect(fix_db) as conn:
        state = conn.execute("SELECT state FROM pipeline_runs WHERE run_id=?", (run_id,)).fetchone()[0]
        ai_jobs = conn.execute("SELECT COUNT(*) FROM jobs WHERE run_id=? AND job_type='AI_ANALYSIS'", (run_id,)).fetchall()

    assert state == MatchState.ANALYZING
    assert len(ai_jobs) == 1


def test_repeated_ticks_are_idempotent_no_duplicate_jobs(fix_db):
    orc = MasterOrchestrator(db_path=fix_db)
    run_id = orc.start_pipeline(10, data_cutoff_at=datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc))

    valid_stats = {"status": "COMPLETED", "sample_size": 10, "coverage": 1.0}

    with sqlite3.connect(fix_db) as conn:
        conn.execute(
            "UPDATE jobs SET status='SUCCESS', result_json=? WHERE run_id=? AND job_type='STATISTICS'",
            (json.dumps(valid_stats), run_id),
        )
        conn.execute("UPDATE pipeline_runs SET state='CALCULATING' WHERE run_id=?", (run_id,))

    orc.tick(run_id)
    orc.tick(run_id)
    orc.tick(run_id)

    with sqlite3.connect(fix_db) as conn:
        ai_jobs_count = conn.execute("SELECT COUNT(*) FROM jobs WHERE run_id=? AND job_type='AI_ANALYSIS'", (run_id,)).fetchone()[0]

    assert ai_jobs_count == 1
