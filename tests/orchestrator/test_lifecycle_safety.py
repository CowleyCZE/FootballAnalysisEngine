import sqlite3
from datetime import datetime, timedelta, timezone

from app.jobs.store import JobStore
from app.orchestrator.recovery import PipelineRecovery
from app.orchestrator.state_machine import MatchState, MatchStateMachine


def test_state_transition_is_atomic_and_audited(tmp_path):
    db = tmp_path / "state.db"
    with sqlite3.connect(db) as conn:
        conn.executescript("""
            CREATE TABLE pipeline_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT UNIQUE NOT NULL,
                state TEXT NOT NULL,
                updated_at TEXT,
                finished_at TEXT
            );
            CREATE TABLE pipeline_state_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                old_state TEXT,
                new_state TEXT NOT NULL,
                reason TEXT,
                created_at TEXT NOT NULL
            );
            CREATE TABLE system_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                run_id TEXT,
                job_id TEXT,
                worker_id TEXT,
                payload_json TEXT,
                created_at TEXT NOT NULL
            );
            INSERT INTO pipeline_runs(run_id,state) VALUES('r1','NEW');
        """)

    machine = MatchStateMachine(str(db))
    assert machine.transition_to("r1", MatchState.DISCOVERY, "start") is True
    assert machine.current_state("r1") == MatchState.DISCOVERY

    with sqlite3.connect(db) as conn:
        history = conn.execute("SELECT old_state,new_state,reason FROM pipeline_state_history").fetchall()
        events = conn.execute("SELECT event_type FROM system_events").fetchall()
    assert history == [("NEW", "DISCOVERY", "start")]
    assert events == [("PIPELINE_STATE_CHANGED",)]
    assert machine.transition_to("r1", MatchState.DISCOVERY, "duplicate") is False


def test_terminal_job_result_is_idempotent(tmp_path):
    db = tmp_path / "jobs.db"
    store = JobStore(str(db))
    store.create_job("j1", "STATISTICS", 1, "r1", {}, "fp1", 50, 3)
    claimed = store.claim("worker-1", ["STATISTICS"])
    assert claimed is not None

    store.finish("j1", "worker-1", True, {"value": 1})
    store.finish("j1", "worker-1", True, {"value": 999})

    with sqlite3.connect(db) as conn:
        row = conn.execute("SELECT status,result_json,attempts FROM jobs WHERE job_id='j1'").fetchone()
        events = conn.execute("SELECT event_type FROM system_events WHERE job_id='j1'").fetchall()
    assert row[0] == "SUCCESS"
    assert '"value": 1' in row[1]
    assert row[2] == 1
    assert [event[0] for event in events].count("JOB_FINISHED") == 1


def test_job_creation_is_idempotent_for_same_fingerprint(tmp_path):
    db = tmp_path / "fingerprint.db"
    store = JobStore(str(db))

    assert store.create_job("j1", "RESEARCH", 1, "r1", {"domain": "FORM_HOME"}, "fp1", 50, 3) == "j1"
    assert store.create_job("j2", "RESEARCH", 1, "r1", {"domain": "FORM_HOME"}, "fp1", 50, 3) is None

    with sqlite3.connect(db) as conn:
        row = conn.execute("SELECT COUNT(*), MIN(job_id) FROM jobs WHERE fingerprint='fp1'").fetchone()
        events = conn.execute("SELECT event_type FROM system_events WHERE job_id IN ('j1','j2')").fetchall()
    assert row == (1, "j1")
    assert [event[0] for event in events] == ["JOB_CREATED"]


def test_dead_worker_recovery_is_restart_safe(tmp_path):
    db = tmp_path / "recovery.db"
    store = JobStore(str(db))
    store.create_job("j1", "STATISTICS", 1, "r1", {}, "fp1", 50, 3)
    claimed = store.claim("worker-1", ["STATISTICS"])
    assert claimed is not None

    stale = (datetime.now(timezone.utc) - timedelta(seconds=500)).isoformat()
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE jobs SET status='RUNNING', heartbeat_at=? WHERE job_id='j1'", (stale,))

    recovery = PipelineRecovery(str(db), timeout_seconds=120)
    assert recovery.recover_dead_workers_and_jobs() == 1
    assert recovery.recover_dead_workers_and_jobs() == 0

    with sqlite3.connect(db) as conn:
        row = conn.execute("SELECT status,worker_id,next_attempt_at FROM jobs WHERE job_id='j1'").fetchone()
        events = conn.execute("SELECT event_type FROM system_events WHERE job_id='j1'").fetchall()
    assert row[0] == "RETRY"
    assert row[1] is None
    assert row[2] is not None
    assert [event[0] for event in events].count("JOB_RECOVERED") == 1
