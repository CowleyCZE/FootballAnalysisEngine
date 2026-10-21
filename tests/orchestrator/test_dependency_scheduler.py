"""TODO 3.1 – závislost je splněna při terminálním stavu (SUCCESS/FAILED/CANCELLED), ne jen úspěchu."""
import sqlite3
from datetime import datetime, timezone

import pytest

from app.database.schema import initialize_database
from app.orchestrator.orchestrator import MasterOrchestrator
from app.orchestrator.scheduler import DependencyScheduler

CUTOFF = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def db(tmp_path):
    path = str(tmp_path / "sched.db")
    initialize_database(path)
    with sqlite3.connect(path) as conn:
        conn.execute("INSERT INTO teams (id, name, normalized_name) VALUES (1, 'Sparta Praha', 'sparta praha'), (2, 'Slavia Praha', 'slavia praha')")
        conn.execute("INSERT INTO competitions (id, name) VALUES (1, 'Chance Liga')")
        conn.execute("INSERT INTO matches (id, home_team_id, away_team_id, competition, competition_id, scheduled_at, status) VALUES (1, 1, 2, 'Chance Liga', 1, '2026-11-10T18:00:00+00:00', 'RESOLVED')")
    return path


def _job_status(db, run_id, domain):
    with sqlite3.connect(db) as conn:
        return conn.execute(
            "SELECT j.status FROM jobs j JOIN research_tasks t ON t.job_id = j.job_id "
            "WHERE t.run_id = ? AND t.domain = ?", (run_id, domain)).fetchone()[0]


def _set_status(db, run_id, domain, status):
    with sqlite3.connect(db) as conn:
        conn.execute(
            "UPDATE jobs SET status = ? WHERE job_id = (SELECT job_id FROM research_tasks WHERE run_id = ? AND domain = ?)",
            (status, run_id, domain))


def test_failed_home_profile_does_not_block_away_profile(db):
    orc = MasterOrchestrator(db_path=db)
    run_id = orc.start_pipeline(1, data_cutoff_at=CUTOFF)
    assert _job_status(db, run_id, "TEAM_PROFILE_AWAY") == "BLOCKED"

    _set_status(db, run_id, "TEAM_PROFILE_HOME", "FAILED")
    assert DependencyScheduler(db).update_blocked_jobs() >= 1

    assert _job_status(db, run_id, "TEAM_PROFILE_AWAY") == "PENDING"


def test_job_stays_blocked_until_dependency_is_terminal(db):
    orc = MasterOrchestrator(db_path=db)
    run_id = orc.start_pipeline(1, data_cutoff_at=CUTOFF)

    _set_status(db, run_id, "TEAM_PROFILE_HOME", "RUNNING")
    DependencyScheduler(db).update_blocked_jobs()
    assert _job_status(db, run_id, "TEAM_PROFILE_AWAY") == "BLOCKED"

    _set_status(db, run_id, "TEAM_PROFILE_HOME", "SUCCESS")
    DependencyScheduler(db).update_blocked_jobs()
    assert _job_status(db, run_id, "TEAM_PROFILE_AWAY") == "PENDING"


def test_failed_required_dependency_still_makes_run_unresolved(db):
    orc = MasterOrchestrator(db_path=db)
    run_id = orc.start_pipeline(1, data_cutoff_at=CUTOFF)
    _set_status(db, run_id, "TEAM_PROFILE_HOME", "FAILED")
    DependencyScheduler(db).update_blocked_jobs()
    # povinný profil domácích selhal (STATISTICS není SUCCESS) => pipeline nesmí být úspěšná
    assert orc._are_all_required_jobs_successful(run_id) is False
