"""TODO 3.2 – STATISTICS čeká na research domény (terminální stav stačí)."""
import sqlite3
from datetime import datetime, timezone

import pytest

from app.database.schema import initialize_database
from app.orchestrator.orchestrator import MasterOrchestrator
from app.orchestrator.scheduler import DependencyScheduler

CUTOFF = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def db(tmp_path):
    path = str(tmp_path / "statdeps.db")
    initialize_database(path)
    with sqlite3.connect(path) as conn:
        conn.execute("INSERT INTO teams (id, name, normalized_name) VALUES (1, 'Sparta Praha', 'sparta praha'), (2, 'Slavia Praha', 'slavia praha')")
        conn.execute("INSERT INTO competitions (id, name) VALUES (1, 'Chance Liga')")
        conn.execute("INSERT INTO matches (id, home_team_id, away_team_id, competition, competition_id, scheduled_at, status) VALUES (1, 1, 2, 'Chance Liga', 1, '2026-11-10T18:00:00+00:00', 'RESOLVED')")
    return path


def test_statistics_job_waits_for_research_jobs_then_runs_on_terminal(db):
    orc = MasterOrchestrator(db_path=db)
    run_id = orc.start_pipeline(1, data_cutoff_at=CUTOFF)
    with sqlite3.connect(db) as conn:
        stat_status = conn.execute("SELECT status FROM jobs WHERE run_id=? AND job_type='STATISTICS'", (run_id,)).fetchone()[0]
        n_deps = conn.execute(
            "SELECT COUNT(*) FROM job_dependencies WHERE job_id=(SELECT id FROM jobs WHERE run_id=? AND job_type='STATISTICS')", (run_id,)).fetchone()[0]
    assert stat_status == "BLOCKED"
    assert n_deps > 0

    # Všechny research joby (kromě profilů) skončí – část selže; statistika se přesto uvolní.
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE jobs SET status='SUCCESS' WHERE run_id=? AND job_type='RESEARCH'", (run_id,))
        conn.execute("UPDATE jobs SET status='FAILED' WHERE id=(SELECT depends_on_job_id FROM job_dependencies WHERE job_id=(SELECT id FROM jobs WHERE run_id=? AND job_type='STATISTICS') LIMIT 1)", (run_id,))
    DependencyScheduler(db).update_blocked_jobs()
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT status FROM jobs WHERE run_id=? AND job_type='STATISTICS'", (run_id,)).fetchone()[0] == "PENDING"


def test_statistics_stays_blocked_while_a_research_job_is_pending(db):
    orc = MasterOrchestrator(db_path=db)
    run_id = orc.start_pipeline(1, data_cutoff_at=CUTOFF)
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE jobs SET status='SUCCESS' WHERE run_id=? AND job_type='RESEARCH'", (run_id,))
        conn.execute("UPDATE jobs SET status='RUNNING' WHERE id=(SELECT depends_on_job_id FROM job_dependencies WHERE job_id=(SELECT id FROM jobs WHERE run_id=? AND job_type='STATISTICS') LIMIT 1)", (run_id,))
    DependencyScheduler(db).update_blocked_jobs()
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT status FROM jobs WHERE run_id=? AND job_type='STATISTICS'", (run_id,)).fetchone()[0] == "BLOCKED"
