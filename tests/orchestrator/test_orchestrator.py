import sqlite3

import pytest

from app.orchestrator.orchestrator import MasterOrchestrator
from app.orchestrator.state_machine import MatchState


@pytest.fixture
def test_db(tmp_path):
    db_file = tmp_path / "test_football.db"
    conn = sqlite3.connect(db_file)
    cursor = conn.cursor()

    cursor.execute("CREATE TABLE teams (id INTEGER PRIMARY KEY, name TEXT);")
    cursor.execute(
        """
        CREATE TABLE matches (
            id INTEGER PRIMARY KEY,
            home_team_id INTEGER NOT NULL,
            away_team_id INTEGER NOT NULL,
            competition TEXT NOT NULL,
            season TEXT,
            scheduled_at TEXT NOT NULL,
            venue TEXT
        );
        """
    )
    cursor.execute("INSERT INTO teams VALUES (1, 'Sparta Praha'), (2, 'Slavia Praha');")
    cursor.execute(
        "INSERT INTO matches VALUES (100, 1, 2, '1. Liga', '2026/27', '2026-10-10 18:00:00', 'Letna');"
    )
    conn.commit()
    conn.close()
    return str(db_file)


def test_start_pipeline_creates_run_and_initial_jobs(test_db):
    orchestrator = MasterOrchestrator(db_path=test_db)

    run_id = orchestrator.start_pipeline(100)

    assert run_id

    with sqlite3.connect(test_db) as conn:
        conn.row_factory = sqlite3.Row
        run = conn.execute(
            "SELECT * FROM pipeline_runs WHERE run_id=?", (run_id,)
        ).fetchone()
        jobs = conn.execute(
            "SELECT job_type, status, run_id FROM jobs WHERE run_id=? ORDER BY id",
            (run_id,),
        ).fetchall()

    assert run is not None
    assert run["match_id"] == 100
    assert run["state"] == MatchState.DISCOVERY
    assert {job["job_type"] for job in jobs} == {"RESEARCH", "STATISTICS"}
    assert all(job["status"] in ("PENDING", "BLOCKED") for job in jobs)
    assert any(job["status"] == "PENDING" for job in jobs)
    assert any(job["status"] == "BLOCKED" for job in jobs)
    assert all(job["run_id"] == run_id for job in jobs)


def test_start_pipeline_rejects_missing_match(test_db):
    orchestrator = MasterOrchestrator(db_path=test_db)

    with pytest.raises(ValueError, match="Match 999 does not exist"):
        orchestrator.start_pipeline(999)
