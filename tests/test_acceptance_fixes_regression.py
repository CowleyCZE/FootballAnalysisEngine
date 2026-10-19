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


def test_daemon_handles_no_result_and_insufficient_data_as_fatal(fix_db):
    from app.workers.daemon import WorkerDaemon
    from app.jobs.models import JobStatus

    daemon = WorkerDaemon(worker_id="test-daemon", capabilities=["RESEARCH"], db_path=fix_db)

    job_id_1 = daemon.queue.create_job("RESEARCH", 10, {"test": 1}, run_id="RUN-D1")
    job_id_2 = daemon.queue.create_job("RESEARCH", 10, {"test": 2}, run_id="RUN-D2")

    # Mock HANDLERS to return NO_RESULT and INSUFFICIENT_DATA
    daemon.HANDLERS = {
        "RESEARCH": lambda payload: {"status": "NO_RESULT" if payload.get("test") == 1 else "INSUFFICIENT_DATA"}
    }

    daemon.run_once()
    daemon.run_once()

    with sqlite3.connect(fix_db) as conn:
        j1 = conn.execute("SELECT status, next_attempt_at FROM jobs WHERE job_id=?", (job_id_1,)).fetchone()
        j2 = conn.execute("SELECT status, next_attempt_at FROM jobs WHERE job_id=?", (job_id_2,)).fetchone()

    assert j1[0] == JobStatus.FAILED
    assert j1[1] is None  # force_fail = True, no next_attempt_at
    assert j2[0] == JobStatus.FAILED
    assert j2[1] is None


def test_idempotent_statistical_snapshots(fix_db):
    from app.statistics.repository import StatisticsRepository

    repo = StatisticsRepository(db_path=fix_db)
    with sqlite3.connect(fix_db) as conn:
        conn.execute("INSERT INTO runs(id, run_id, status, started_at) VALUES (500, 'RUN-IDEMP-1', 'RUNNING', '2026-10-04T10:00:00Z')")

    # Insert snapshot twice with identical key
    id1 = repo.save_snapshot(500, 10, 1, "form_points", 12.0, 5, 1.0, "2026-10-04T12:00:00Z")
    id2 = repo.save_snapshot(500, 10, 1, "form_points", 12.0, 5, 1.0, "2026-10-04T12:00:00Z")

    with sqlite3.connect(fix_db) as conn:
        rows = conn.execute("SELECT COUNT(*) FROM statistical_snapshots WHERE run_id=500 AND metric='form_points'").fetchone()[0]

    assert rows == 1


def test_menu_select_run_by_sequence_number_and_run_id(fix_db, monkeypatch):
    import menu
    monkeypatch.setattr(menu, "DB_PATH", fix_db)

    with sqlite3.connect(fix_db) as conn:
        conn.execute("INSERT INTO runs(id, run_id, status, started_at) VALUES (601, 'RUN-M-1', 'RUNNING', '2026-10-04T10:00:00Z')")
        conn.execute("INSERT INTO pipeline_runs(run_id, match_id, state, cycle, max_cycles, started_at, updated_at) VALUES ('RUN-M-1', 10, 'DISCOVERY', 1, 3, '2026-10-04T10:00:00Z', '2026-10-04T10:00:00Z')")

    monkeypatch.setattr("builtins.input", lambda _prompt="": "1")
    run_selected = menu.select_run()
    assert run_selected is not None
    assert run_selected["run_id"] == "RUN-M-1"

    monkeypatch.setattr("builtins.input", lambda _prompt="": "RUN-M-1")
    run_selected_2 = menu.select_run()
    assert run_selected_2 is not None
    assert run_selected_2["run_id"] == "RUN-M-1"


def test_note9_worker_sanitize_url_and_text(monkeypatch):
    from scripts.note9_worker import sanitize_url, sanitize_text

    monkeypatch.setenv("WORKER_API_TOKEN", "super-secret-token")

    url = "http://admin:password123@192.168.1.1:8000/api/internal/search?query=test&key=val"
    sanitized = sanitize_url(url)
    assert "password123" not in sanitized
    assert "admin:***@" in sanitized
    assert "?[redacted]" in sanitized

    text = "Failed to call http://example.com with token super-secret-token"
    clean = sanitize_text(text)
    assert "super-secret-token" not in clean
    assert "[REDACTED_TOKEN]" in clean


def test_init_database_deduplicates_snapshots_before_unique_index(tmp_path):
    from scripts.init_database import init_db

    db_path = tmp_path / "database" / "football.db"
    db_path.parent.mkdir()
    with sqlite3.connect(db_path) as conn:
        conn.executescript("""
            CREATE TABLE statistical_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL,
                match_id INTEGER,
                team_id INTEGER,
                metric TEXT NOT NULL,
                value REAL,
                sample_size INTEGER,
                coverage REAL,
                data_cutoff_at TEXT NOT NULL,
                calculation_version TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            INSERT INTO statistical_snapshots
                (run_id, team_id, metric, value, data_cutoff_at, calculation_version)
            VALUES
                (1, 7, 'form_points', 2, '2026-10-11T12:00:00Z', '1.0.0'),
                (1, 7, 'form_points', 3, '2026-10-11T12:00:00Z', '1.0.0');
        """)

    # Exercise the production init script against this isolated DB path.
    init_db(db_path)

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT value FROM statistical_snapshots WHERE run_id=1 AND team_id=7 AND metric='form_points'"
        ).fetchall()
        indexes = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='uidx_statistical_snapshots_stable'"
        ).fetchall()
    assert rows == [(3.0,)]
    assert indexes == [("uidx_statistical_snapshots_stable",)]

def test_note9_worker_remote_disconnected_reconnect_and_no_job(monkeypatch):
    from scripts.note9_worker import Note9Worker, DEFAULT_CONFIG
    import requests

    monkeypatch.setenv("WORKER_API_TOKEN", "test-token")
    worker = Note9Worker(dict(DEFAULT_CONFIG))

    responses = [
        requests.exceptions.ConnectionError("RemoteDisconnected: Remote end closed connection without response"),
        requests.exceptions.ConnectionError("RemoteDisconnected: Remote end closed connection without response"),
        requests.exceptions.ConnectionError("RemoteDisconnected: Remote end closed connection without response"),
    ]

    def mock_request(method, url, **kwargs):
        if responses:
            res = responses.pop(0)
            if isinstance(res, Exception):
                raise res
            return res
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"status": "no_job"}
        mock_resp.raise_for_status = MagicMock()
        return mock_resp

    from unittest.mock import MagicMock
    monkeypatch.setattr(worker.session, "request", mock_request)

    # Initial request fails due to RemoteDisconnected
    with pytest.raises(RuntimeError, match="RemoteDisconnected"):
        worker.claim()

    assert not worker.is_online
    assert worker.consecutive_failures == 1

    # Next request succeeds with no_job
    job = worker.claim()
    assert job is None
    assert worker.is_online
    assert worker.consecutive_failures == 0


def test_search_diagnostics_recorded_and_warning_generated():
    from app.search.engine import SearchEngine
    from app.search.models import QuerySpec
    from app.research.engine import ResearchEngine
    from app.research.models import ResearchTask
    import asyncio
    from datetime import datetime, timezone

    class MockSearXNGClient:
        async def search(self, query, language="all", time_range=None):
            return {
                "results": [
                    {
                        "title": "Arsenal vs Chelsea post-cutoff news",
                        "url": "https://sports.example/post-cutoff",
                        "content": "Arsenal vs Chelsea news",
                        "published_at": "2026-10-05T10:00:00Z",
                    }
                ]
            }

    search_engine = SearchEngine(client=MockSearXNGClient())
    results = asyncio.run(
        search_engine.search(
            QuerySpec(query="Arsenal Chelsea"),
            team="Arsenal",
            data_cutoff_at=datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc),
        )
    )

    assert len(results) == 0
    assert search_engine.last_diagnostics is not None
    assert search_engine.last_diagnostics.raw_count == 1
    assert search_engine.last_diagnostics.cutoff_filtered_count == 0
    assert len(search_engine.last_diagnostics.drop_reasons) > 0


def test_optional_domain_failure_does_not_block_pipeline(fix_db):
    orc = MasterOrchestrator(db_path=fix_db)
    run_id = orc.start_pipeline(10, data_cutoff_at=datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc))

    with sqlite3.connect(fix_db) as conn:
        # Mark required jobs as SUCCESS
        conn.execute("UPDATE jobs SET status='SUCCESS', result_json='{\"status\": \"SUCCESS\"}' WHERE run_id=? AND job_type IN ('RESEARCH', 'STATISTICS')", (run_id,))
        # Mark optional job as FAILED
        conn.execute("INSERT INTO jobs(job_id, run_id, match_id, job_type, status, priority, payload_json) VALUES ('OPT-1', ?, 10, 'RESEARCH', 'FAILED', 30, '{\"required\": false, \"domain\": \"WEATHER\"}')", (run_id,))

    orc.tick(run_id)

    with sqlite3.connect(fix_db) as conn:
        state = conn.execute("SELECT state FROM pipeline_runs WHERE run_id=?", (run_id,)).fetchone()[0]

    assert state not in ("UNRESOLVED", "FAILED", "DISCOVERY")
