import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.jobs.models import JobStatus
from app.jobs.queue import JobQueue
from app.jobs.worker import BaseWorkerDaemon
from app.orchestrator.orchestrator import MasterOrchestrator
from app.workers.ai_worker import AIWorker
from app.workers.audit_worker import AuditWorker
from app.workers.crawler_worker import CrawlerWorker
from app.workers.search_worker import SearchWorker
from app.workers.statistics_worker import StatisticsWorker


@pytest.fixture
def test_db(tmp_path):
    db_path = tmp_path / "test_pipeline.db"
    schema = Path(__file__).resolve().parents[2] / "database" / "schema.sql"
    with sqlite3.connect(db_path) as conn:
        conn.executescript(schema.read_text(encoding="utf-8"))
        conn.execute("INSERT INTO teams(name, normalized_name, competition) VALUES (?, ?, ?)", ("Test Home FC", "test_home_fc", "Test League"))
        home_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute("INSERT INTO teams(name, normalized_name, competition) VALUES (?, ?, ?)", ("Test Away FC", "test_away_fc", "Test League"))
        away_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            "INSERT INTO matches(external_match_id, competition, season, home_team_id, away_team_id, scheduled_at, status) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("TEST-MATCH-123", "Test League", "2026/27", home_id, away_id, "2026-10-04T20:00:00+00:00", "SCHEDULED"),
        )
        assert conn.execute("SELECT last_insert_rowid()").fetchone()[0] == 1
        conn.commit()
    return str(db_path)


def test_01_create_pipeline(test_db):
    orc = MasterOrchestrator(db_path=test_db)
    run_id = orc.start_pipeline(1)
    assert run_id is not None
    assert "M1" in run_id


def test_02_automatic_job_creation(test_db):
    orc = MasterOrchestrator(db_path=test_db)
    run_id = orc.start_pipeline(1)

    with sqlite3.connect(test_db) as conn:
        count = conn.execute("SELECT COUNT(*) FROM jobs WHERE match_id = 1 AND run_id = ?", (run_id,)).fetchone()[0]
    assert count >= 2


def test_03_04_worker_claim_and_multi_worker(test_db):
    orc = MasterOrchestrator(db_path=test_db)
    orc.start_pipeline(1)

    w1 = BaseWorkerDaemon(worker_id="notebook-01", capabilities=["SEARCH"], db_path=test_db)
    w2 = BaseWorkerDaemon(worker_id="note9-01", capabilities=["SEARCH"], db_path=test_db)

    handlers = {"SEARCH": SearchWorker.execute}
    p1 = w1.process_next_job(handlers)
    p2 = w2.process_next_job(handlers)

    assert p1 or p2


def test_05_06_worker_crash_recovery_and_retry_limit(test_db):
    queue = JobQueue(db_path=test_db)
    j_id = queue.create_job("SEARCH", 1, {"query": "fail"}, max_attempts=2)

    job = queue.claim_job("worker-dead", ["SEARCH"])
    assert job is not None
    with sqlite3.connect(test_db) as conn:
        old_time = (datetime.now(timezone.utc) - timedelta(seconds=200)).isoformat()
        conn.execute("UPDATE jobs SET heartbeat_at = ? WHERE job_id = ?", (old_time, j_id))
        conn.commit()

    orc = MasterOrchestrator(db_path=test_db)
    orc.recovery.recover_dead_workers_and_jobs()

    with sqlite3.connect(test_db) as conn:
        row = conn.execute("SELECT status, attempts FROM jobs WHERE job_id = ?", (j_id,)).fetchone()
    assert row[0] == "RETRY"
    assert row[1] == 1


def test_07_job_dependencies(test_db):
    queue = JobQueue(db_path=test_db)
    j1_id = queue.create_job("SEARCH", 1, {"query": "1"})

    with sqlite3.connect(test_db) as conn:
        j1_pk = conn.execute("SELECT id FROM jobs WHERE job_id = ?", (j1_id,)).fetchone()[0]

    j2_id = queue.create_job("CRAWL", 1, {"url": "2"}, depends_on_pks=[j1_pk])

    with sqlite3.connect(test_db) as conn:
        status = conn.execute("SELECT status FROM jobs WHERE job_id = ?", (j2_id,)).fetchone()[0]
    assert status == JobStatus.BLOCKED


def test_13_duplicate_research_job_protection(test_db):
    queue = JobQueue(db_path=test_db)
    j1 = queue.create_job("RESEARCH", 1, {"reason": "check injury"})
    j2 = queue.create_job("RESEARCH", 1, {"reason": "check injury"})

    assert j1 is not None
    assert j2 is None


def test_14_deadlock_detection(test_db):
    queue = JobQueue(db_path=test_db)
    j1_id = queue.create_job("SEARCH", 1, {"q": "1"})

    with sqlite3.connect(test_db) as conn:
        j1_pk = conn.execute("SELECT id FROM jobs WHERE job_id = ?", (j1_id,)).fetchone()[0]

    with pytest.raises(ValueError, match="Deadlock detected"):
        queue.add_dependency(j1_pk, j1_pk)

    j2_id = queue.create_job("CRAWL", 1, {"q": "2"}, depends_on_pks=[j1_pk])
    with sqlite3.connect(test_db) as conn:
        j2_pk = conn.execute("SELECT id FROM jobs WHERE job_id = ?", (j2_id,)).fetchone()[0]

    with pytest.raises(ValueError, match="Deadlock detected"):
        queue.add_dependency(j1_pk, j2_pk)


def test_15_full_autonomous_pipeline(test_db):
    """Exercise the complete orchestrator/worker lifecycle without live internet or Ollama.

    External boundaries are replaced with deterministic fixtures. The real JobQueue,
    worker daemon, orchestrator, state machine, scheduler, recovery and persistence
    remain active. Live SearXNG/crawler/Ollama integration is tested separately.
    """
    orc = MasterOrchestrator(db_path=test_db)
    run_id = orc.start_pipeline(1)

    worker = BaseWorkerDaemon(
        worker_id="notebook-01",
        capabilities=["SEARCH", "CRAWL", "STATISTICS", "AI_ANALYSIS", "AUDIT", "RESEARCH"],
        db_path=test_db,
    )

    def fixture_search(_payload):
        return {
            "status": "COMPLETED",
            "query": "fixture",
            "results": [
                {
                    "title": "Fixture source",
                    "url": "https://fixture.test/match-report",
                    "snippet": "Deterministic integration-test source",
                    "engine": "fixture",
                }
            ],
            "result_count": 1,
            "source": "fixture",
        }

    def fixture_crawl(_payload):
        return {
            "status": "COMPLETED",
            "url": "https://fixture.test/match-report",
            "final_url": "https://fixture.test/match-report",
            "status_code": 200,
            "content_length": 1024,
            "used_playwright": False,
            "content_hash": "fixture-content-hash",
            "title": "Fixture match report",
            "word_count": 100,
            "quality_score": 1.0,
        }

    def fixture_ai(_payload):
        return {
            "status": "COMPLETED",
            "analysis_status": "sufficient_data",
            "confidence": 0.8,
            "key_factors": [],
            "claims": [],
            "uncertainties": [],
            "input_hash": "fixture-input-hash",
            "output_hash": "fixture-output-hash",
        }

    def fixture_audit(_payload):
        return {
            "status": "AUDIT_COMPLETE",
            "pipeline_status": "PASS",
            "research_required": False,
            "issues": [],
            "score": 1.0,
        }

    handlers = {
        "SEARCH": fixture_search,
        "CRAWL": fixture_crawl,
        "STATISTICS": StatisticsWorker.execute,
        "AI_ANALYSIS": fixture_ai,
        "AUDIT": fixture_audit,
        "RESEARCH": lambda _payload: {"status": "resolved"},
    }

    for _ in range(25):
        orc.tick(run_id)
        worker.process_next_job(handlers)

    # One final scheduler/orchestrator tick consumes the last successful job.
    orc.tick(run_id)

    with sqlite3.connect(test_db) as conn:
        final_state = conn.execute("SELECT state FROM pipeline_runs WHERE run_id = ?", (run_id,)).fetchone()[0]
    assert final_state in ["COMPLETED", "UNRESOLVED", "FINALIZING"]
