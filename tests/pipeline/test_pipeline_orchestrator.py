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
    return str(tmp_path / "test_pipeline.db")

def test_01_create_pipeline(test_db):
    orc = MasterOrchestrator(db_path=test_db)
    run_id = orc.start_pipeline(123)
    assert run_id is not None
    assert "M123" in run_id

def test_02_automatic_job_creation(test_db):
    orc = MasterOrchestrator(db_path=test_db)
    run_id = orc.start_pipeline(123)
    
    conn = sqlite3.connect(test_db)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM jobs WHERE match_id = 123")
    count = cursor.fetchone()[0]
    conn.close()
    assert count >= 2

def test_03_04_worker_claim_and_multi_worker(test_db):
    orc = MasterOrchestrator(db_path=test_db)
    orc.start_pipeline(123)

    w1 = BaseWorkerDaemon(worker_id="notebook-01", capabilities=["SEARCH"], db_path=test_db)
    w2 = BaseWorkerDaemon(worker_id="note9-01", capabilities=["SEARCH"], db_path=test_db)

    handlers = {"SEARCH": SearchWorker.execute}
    p1 = w1.process_next_job(handlers)
    p2 = w2.process_next_job(handlers)

    assert p1 or p2

def test_05_06_worker_crash_recovery_and_retry_limit(test_db):
    queue = JobQueue(db_path=test_db)
    j_id = queue.create_job("SEARCH", 123, {"query": "fail"}, max_attempts=2)
    
    # Claim job a simulace zamrznutí
    job = queue.claim_job("worker-dead", ["SEARCH"])
    conn = sqlite3.connect(test_db)
    old_time = (datetime.now(timezone.utc) - timedelta(seconds=200)).isoformat()
    conn.execute("UPDATE jobs SET heartbeat_at = ? WHERE job_id = ?", (old_time, j_id))
    conn.commit()
    conn.close()

    orc = MasterOrchestrator(db_path=test_db)
    orc.recovery.recover_dead_workers_and_jobs()

    conn = sqlite3.connect(test_db)
    cursor = conn.cursor()
    cursor.execute("SELECT status, attempts FROM jobs WHERE job_id = ?", (j_id,))
    row = cursor.fetchone()
    conn.close()

    assert row[0] == "RETRY"
    assert row[1] == 1

def test_07_job_dependencies(test_db):
    queue = JobQueue(db_path=test_db)
    j1_id = queue.create_job("SEARCH", 123, {"query": "1"})
    
    conn = sqlite3.connect(test_db)
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM jobs WHERE job_id = ?", (j1_id,))
    j1_pk = cursor.fetchone()[0]
    conn.close()

    j2_id = queue.create_job("CRAWL", 123, {"url": "2"}, depends_on_pks=[j1_pk])

    conn = sqlite3.connect(test_db)
    cursor = conn.cursor()
    cursor.execute("SELECT status FROM jobs WHERE job_id = ?", (j2_id,))
    assert cursor.fetchone()[0] == JobStatus.BLOCKED
    conn.close()

def test_13_duplicate_research_job_protection(test_db):
    queue = JobQueue(db_path=test_db)
    j1 = queue.create_job("RESEARCH", 123, {"reason": "check injury"})
    j2 = queue.create_job("RESEARCH", 123, {"reason": "check injury"})

    assert j1 is not None
    assert j2 is None

def test_14_deadlock_detection(test_db):
    queue = JobQueue(db_path=test_db)
    j1_id = queue.create_job("SEARCH", 123, {"q": "1"})
    
    conn = sqlite3.connect(test_db)
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM jobs WHERE job_id = ?", (j1_id,))
    j1_pk = cursor.fetchone()[0]
    conn.close()

    with pytest.raises(ValueError, match="Deadlock detected"):
        queue.add_dependency(j1_pk, j1_pk)

    j2_id = queue.create_job("CRAWL", 123, {"q": "2"}, depends_on_pks=[j1_pk])
    conn = sqlite3.connect(test_db)
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM jobs WHERE job_id = ?", (j2_id,))
    j2_pk = cursor.fetchone()[0]
    conn.close()

    with pytest.raises(ValueError, match="Deadlock detected"):
        queue.add_dependency(j1_pk, j2_pk)

def test_15_full_autonomous_pipeline(test_db):
    orc = MasterOrchestrator(db_path=test_db)
    run_id = orc.start_pipeline(123)

    worker = BaseWorkerDaemon(
        worker_id="notebook-01",
        capabilities=["SEARCH", "CRAWL", "STATISTICS", "AI_ANALYSIS", "AUDIT", "RESEARCH"],
        db_path=test_db
    )

    handlers = {
        "SEARCH": SearchWorker.execute,
        "CRAWL": CrawlerWorker.execute,
        "STATISTICS": StatisticsWorker.execute,
        "AI_ANALYSIS": AIWorker.execute,
        "AUDIT": AuditWorker.execute,
        "RESEARCH": lambda p: {"status": "resolved"}
    }

    for _ in range(25):
        orc.tick(run_id)
        worker.process_next_job(handlers)

    conn = sqlite3.connect(test_db)
    cursor = conn.cursor()
    cursor.execute("SELECT state FROM pipeline_runs WHERE run_id = ?", (run_id,))
    final_state = cursor.fetchone()[0]
    conn.close()

    assert final_state in ["COMPLETED", "UNRESOLVED", "FINALIZING"]
