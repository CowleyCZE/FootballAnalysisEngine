"""Běh M976_e7ab: povinná doména ABSENCES_* s `NO_RESULT` nesmí 3 cykly blokovat coverage (tip i AI byly hotové)."""
import sqlite3

import pytest

from app.database.schema import initialize_database
from app.orchestrator.coverage import CoverageEngine


@pytest.fixture
def db(tmp_path):
    path = str(tmp_path / "cov.db")
    initialize_database(path)
    with sqlite3.connect(path) as conn:
        conn.execute("INSERT INTO teams (id, name, normalized_name) VALUES (1, 'Zlín', 'zlin')")
        conn.execute("INSERT INTO teams (id, name, normalized_name) VALUES (2, 'Slovácko', 'slovacko')")
        conn.execute("INSERT INTO matches (id, home_team_id, away_team_id, competition, scheduled_at, status) "
                     "VALUES (10, 1, 2, 'Chance Liga', '2026-11-07T14:00:00+00:00', 'RESOLVED')")
        conn.execute("INSERT INTO runs(id, run_id, status, started_at) VALUES (1, 'R1', 'RUNNING', '2026-11-01T10:00:00Z')")
    return path


def _task(path, idx, domain, status, required=1):
    with sqlite3.connect(path) as conn:
        conn.execute(
            "INSERT INTO research_tasks(id, run_id, run_db_id, match_id, task_uuid, domain, task_type, description, "
            "required, priority, capabilities_json, data_cutoff_at, home_team, away_team, competition, scheduled_at, status) "
            "VALUES (?, 'R1', 1, 10, ?, ?, 'FACT_COLLECTION', 't', ?, 50, '[]', '2026-11-01T12:00:00Z', 'Zlín', "
            "'Slovácko', 'Chance Liga', '2026-11-07T14:00:00Z', ?)",
            (idx, f"U{idx}", domain, required, status))


def test_absences_no_result_does_not_block(db):
    _task(db, 1, "TEAM_PROFILE_HOME", "SUCCESS")
    _task(db, 2, "ABSENCES_HOME", "NO_RESULT")
    _task(db, 3, "ABSENCES_AWAY", "SUCCESS")
    assert CoverageEngine(db).evaluate_run("R1", 1).ready


def test_profile_no_result_still_blocks(db):
    _task(db, 1, "TEAM_PROFILE_HOME", "NO_RESULT")
    _task(db, 2, "ABSENCES_HOME", "SUCCESS")
    ready = CoverageEngine(db).evaluate_run("R1", 1)
    assert not ready.ready
    assert "TEAM_PROFILE_HOME" in ready.blocking_reasons[0]
