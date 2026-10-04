import sqlite3
from datetime import datetime, timezone, timedelta

from app.jobs.models import JobStatus
from app.jobs.store import JobStore
from app.orchestrator.recovery import PipelineRecovery
from app.orchestrator.scheduler import DependencyScheduler


def test_job_store_enforces_required_worker_capabilities(tmp_path):
    db = str(tmp_path / "jobs.db")
    store = JobStore(db)
    store.create_job(
        job_id="job-1",
        job_type="RESEARCH",
        match_id=1,
        run_id="run-1",
        payload={"capabilities_required": ["browser", "http_fetch"]},
        fingerprint="fp-1",
        priority=50,
        max_attempts=3,
    )

    assert store.claim("worker-http", ["http_fetch"]) is None
    claimed = store.claim("worker-browser", ["browser", "http_fetch"])
    assert claimed is not None
    assert claimed["attempt_number"] == 1


def test_dependency_scheduler_unblocks_only_after_all_dependencies_succeed(tmp_path):
    db = str(tmp_path / "deps.db")
    store = JobStore(db)
    first = store.create_job("first", "A", 1, "run", {}, "fp-a", 50, 1)
    second = store.create_job("second", "B", 1, "run", {}, "fp-b", 50, 1)
    assert first and second
    store.add_dependency = None
    with store.connect() as conn:
        first_pk = conn.execute("SELECT id FROM jobs WHERE job_id='first'").fetchone()[0]
        second_pk = conn.execute("SELECT id FROM jobs WHERE job_id='second'").fetchone()[0]
        conn.execute("INSERT INTO job_dependencies(job_id, depends_on_job_id) VALUES (?, ?)", (second_pk, first_pk))
        conn.execute("UPDATE jobs SET status='BLOCKED' WHERE job_id='second'")

    scheduler = DependencyScheduler(db)
    assert scheduler.update_blocked_jobs() == 0
    with store.connect() as conn:
        conn.execute("UPDATE jobs SET status='SUCCESS' WHERE job_id='first'")
    assert scheduler.update_blocked_jobs() == 1
    with store.connect() as conn:
        status = conn.execute("SELECT status FROM jobs WHERE job_id='second'").fetchone()[0]
    assert status == JobStatus.PENDING


def test_recovery_requeues_research_job_and_updates_task(tmp_path):
    db = str(tmp_path / "recovery.db")
    store = JobStore(db)
    store.create_job("research-job", "RESEARCH", 50, "run-1", {}, "fp-r", 80, 3)
    with store.connect() as conn:
        job = conn.execute("SELECT id FROM jobs WHERE job_id='research-job'").fetchone()
        conn.execute("CREATE TABLE research_tasks (id INTEGER PRIMARY KEY, job_id TEXT, status TEXT, attempt_number INTEGER, updated_at TEXT)")
        conn.execute("CREATE TABLE research_executions (id INTEGER PRIMARY KEY, task_id INTEGER, status TEXT, completed_at TEXT, error_message TEXT)")
        conn.execute("INSERT INTO research_tasks VALUES (1, 'research-job', 'RUNNING', 1, '')")
        conn.execute("INSERT INTO research_executions VALUES (1, 1, 'RUNNING', NULL, NULL)")
        stale = (datetime.now(timezone.utc) - timedelta(seconds=600)).isoformat()
        conn.execute("UPDATE jobs SET status='RUNNING', attempts=1, heartbeat_at=?, worker_id=NULL WHERE id=?", (stale, job[0]))

    recovered = PipelineRecovery(db, timeout_seconds=120).recover_dead_workers_and_jobs()
    assert recovered == 1
    with sqlite3.connect(db) as conn:
        task = conn.execute("SELECT status, attempt_number FROM research_tasks WHERE id=1").fetchone()
        execution = conn.execute("SELECT status FROM research_executions WHERE id=1").fetchone()
    assert task[0] == "QUEUED"
    assert task[1] == 1
    assert execution[0] == "RETRY"
