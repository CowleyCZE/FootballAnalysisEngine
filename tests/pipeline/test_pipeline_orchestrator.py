import pytest
import time
import sqlite3
from datetime import datetime, timedelta, timezone

from app.orchestrator.orchestrator import MasterOrchestrator
from app.jobs.queue import JobQueue
from app.jobs.models import JobStatus
from app.jobs.worker import BaseWorkerDaemon
from app.workers.search_worker import SearchWorker
from app.workers.crawler_worker import CrawlerWorker
from app.workers.statistics_worker import StatisticsWorker
from app.workers.ai_worker import AIWorker
from app.workers.audit_worker import AuditWorker


@pytest.fixture
def test_db(tmp_path):
    db = str(tmp_path / "test_pipeline.db")
    MasterOrchestrator(db_path=db)
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO teams(id, name, normalized_name) VALUES (1, 'Home FC', 'home_fc'), (2, 'Away FC', 'away_fc')")
        conn.execute("INSERT INTO matches(id, competition, season, home_team_id, away_team_id, scheduled_at, venue) VALUES (123, 'Test League', '2026/27', 1, 2, '2026-10-10T18:00:00', 'Test Stadium')")
        conn.commit()
    return db


def test_01_create_pipeline(test_db):
    orc = MasterOrchestrator(db_path=test_db)
    run_id = orc.start_pipeline(123)
    assert run_id is not None
    assert "M123" in run_id


def test_02_automatic_job_creation(test_db):
    orc = MasterOrchestrator(db_path=test_db)
    run_id = orc.start_pipeline(123)
    with sqlite3.connect(test_db) as conn:
        count = conn.execute("SELECT COUNT(*) FROM jobs WHERE match_id = 123").fetchone()[0]
    assert count >= 2


def test_03_04_worker_claim_and_multi_worker(test_db):
    orc = MasterOrchestrator(db_path=test_db)
    orc.start_pipeline(123)
    w1 = BaseWorkerDaemon(worker_id="notebook-01", capabilities=["RESEARCH", "STATISTICS"], db_path=test_db)
    w2 = BaseWorkerDaemon(worker_id="note9-01", capabilities=["RESEARCH", "STATISTICS"], db_path=test_db)
    handlers = {"RESEARCH": lambda p: {"status": "ok"}, "STATISTICS": StatisticsWorker.execute}
    p1 = w1.process_next_job(handlers)
    p2 = w2.process_next_job(handlers)
    assert p1 or p2


def test_05_06_worker_crash_recovery_and_retry_limit(test_db):
    queue = JobQueue(db_path=test_db)
    j_id = queue.create_job("SEARCH", 123, {"query": "fail"}, max_attempts=2)
    job = queue.claim_job("worker-dead", ["SEARCH"])
    with sqlite3.connect(test_db) as conn:
        old_time = (datetime.now(timezone.utc) - timedelta(seconds=400)).isoformat()
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
    j1_id = queue.create_job("SEARCH", 123, {"query": "1"})
    with sqlite3.connect(test_db) as conn:
        j1_pk = conn.execute("SELECT id FROM jobs WHERE job_id = ?", (j1_id,)).fetchone()[0]
    j2_id = queue.create_job("CRAWL", 123, {"url": "2"}, depends_on_pks=[j1_pk])
    with sqlite3.connect(test_db) as conn:
        assert conn.execute("SELECT status FROM jobs WHERE job_id = ?", (j2_id,)).fetchone()[0] == JobStatus.BLOCKED


def test_13_duplicate_research_job_protection(test_db):
    queue = JobQueue(db_path=test_db)
    j1 = queue.create_job("RESEARCH", 123, {"reason": "check injury"})
    j2 = queue.create_job("RESEARCH", 123, {"reason": "check injury"})
    assert j1 is not None
    assert j2 is None


def test_14_deadlock_detection(test_db):
    queue = JobQueue(db_path=test_db)
    j1_id = queue.create_job("SEARCH", 123, {"q": "1"})
    with sqlite3.connect(test_db) as conn:
        j1_pk = conn.execute("SELECT id FROM jobs WHERE job_id = ?", (j1_id,)).fetchone()[0]
    with pytest.raises(ValueError, match="Deadlock detected"):
        queue.add_dependency(j1_pk, j1_pk)
    j2_id = queue.create_job("CRAWL", 123, {"q": "2"}, depends_on_pks=[j1_pk])
    with sqlite3.connect(test_db) as conn:
        j2_pk = conn.execute("SELECT id FROM jobs WHERE job_id = ?", (j2_id,)).fetchone()[0]
    with pytest.raises(ValueError, match="Deadlock detected"):
        queue.add_dependency(j1_pk, j2_pk)


def test_15_full_autonomous_pipeline(test_db):
    orc = MasterOrchestrator(db_path=test_db)
    run_id = orc.start_pipeline(123)
    worker = BaseWorkerDaemon(worker_id="notebook-01", capabilities=["SEARCH", "CRAWL", "STATISTICS", "AI_ANALYSIS", "AUDIT", "RESEARCH"], db_path=test_db)
    handlers = {
        "SEARCH": SearchWorker.execute,
        "CRAWL": CrawlerWorker.execute,
        "STATISTICS": StatisticsWorker.execute,
        "AI_ANALYSIS": AIWorker.execute,
        "AUDIT": AuditWorker.execute,
        "RESEARCH": lambda p: {"status": "resolved"},
    }
    for _ in range(25):
        orc.tick(run_id)
        worker.process_next_job(handlers)
    with sqlite3.connect(test_db) as conn:
        final_state = conn.execute("SELECT state FROM pipeline_runs WHERE run_id = ?", (run_id,)).fetchone()[0]
    assert final_state in ["COMPLETED", "UNRESOLVED", "FINALIZING"]
