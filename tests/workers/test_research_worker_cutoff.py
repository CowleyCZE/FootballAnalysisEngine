import sqlite3
import pytest
from datetime import datetime, timezone
from app.workers.research_worker import ResearchWorker
from app.database.schema import initialize_database


@pytest.fixture
def test_db(tmp_path):
    db_file = str(tmp_path / "test_rw.db")
    initialize_database(db_file)
    with sqlite3.connect(db_file) as conn:
        conn.execute("INSERT INTO teams(id, name, normalized_name) VALUES (1, 'Arsenal', 'arsenal')")
        conn.execute("INSERT INTO teams(id, name, normalized_name) VALUES (2, 'Chelsea', 'chelsea')")
        conn.execute(
            "INSERT INTO matches(id, competition, home_team_id, away_team_id, scheduled_at, status) VALUES (10, 'Premier League', 1, 2, '2026-10-04T15:00:00Z', 'RESOLVED')"
        )
    return db_file


def test_missing_kickoff_and_missing_cutoff(test_db):
    worker = ResearchWorker(db_path=test_db)
    payload = {
        "match_id": 999,
        "domain": "GENERAL",
        "home_team": "Team A",
        "away_team": "Team B",
        "competition": "League",
    }
    res = worker.run_execute(payload)
    assert res["status"] == "FAILED"
    assert "Match kickoff time" in res["error"] or "Context resolution failed" in res["error"]


def test_kickoff_exists_and_cutoff_is_resolved(test_db):
    worker = ResearchWorker(db_path=test_db)
    payload = {
        "match_id": 10,
        "domain": "GENERAL",
        "scheduled_at": "2026-10-04T15:00:00Z",
    }
    ctx = worker._resolve_match_context(10, payload, {})
    assert ctx["scheduled_at"] == datetime(2026, 10, 4, 15, 0, tzinfo=timezone.utc)
    assert ctx["data_cutoff_at"] == datetime(2026, 10, 4, 15, 0, tzinfo=timezone.utc)


def test_cutoff_exists_but_kickoff_is_missing(test_db):
    worker = ResearchWorker(db_path=test_db)
    payload = {
        "match_id": 999,
        "domain": "GENERAL",
        "data_cutoff_at": "2026-10-04T12:00:00Z",
    }
    res = worker.run_execute(payload)
    assert res["status"] == "FAILED"
    assert "kickoff" in res["error"].lower() or "scheduled_at" in res["error"].lower()


def test_invalid_kickoff_timestamp(test_db):
    worker = ResearchWorker(db_path=test_db)
    payload = {
        "match_id": 999,
        "domain": "GENERAL",
        "scheduled_at": "not-a-valid-date",
        "data_cutoff_at": "2026-10-04T12:00:00Z",
    }
    res = worker.run_execute(payload)
    assert res["status"] == "FAILED"
    assert "Invalid timestamp" in res["error"] or "Context resolution failed" in res["error"]


def test_invalid_cutoff_timestamp(test_db):
    worker = ResearchWorker(db_path=test_db)
    payload = {
        "match_id": 10,
        "domain": "GENERAL",
        "scheduled_at": "2026-10-04T15:00:00Z",
        "data_cutoff_at": "invalid-cutoff",
    }
    res = worker.run_execute(payload)
    assert res["status"] == "FAILED"
    assert "Invalid timestamp" in res["error"] or "Context resolution failed" in res["error"]


def test_invalid_timezone(test_db):
    worker = ResearchWorker(db_path=test_db)
    payload = {
        "match_id": 10,
        "domain": "GENERAL",
        "scheduled_at": "2026-10-04T15:00:00",
        "timezone": "NonExistent/Timezone_Name_123",
    }
    res = worker.run_execute(payload)
    assert res["status"] == "FAILED"
    assert "Invalid timestamp" in res["error"] or "neznámé časové pásmo" in res["error"].lower()


def test_valid_verified_match_works(test_db):
    class MockEngine:
        def execute(self, task):
            from app.research.research_result import ResearchResult, ResearchMetrics
            from app.research.models import ResearchStatus
            return ResearchResult(task_id=task.task_id, execution_id="EXEC-1", status=ResearchStatus.SUCCESS, claims=[], metrics=ResearchMetrics())

    worker = ResearchWorker(db_path=test_db, engine=MockEngine())
    payload = {
        "match_id": 10,
        "domain": "GENERAL",
        "run_id": "RUN-1",
        "scheduled_at": "2026-10-04T15:00:00Z",
        "data_cutoff_at": "2026-10-04T12:00:00Z",
    }
    res = worker.run_execute(payload)
    assert res["status"] == "SUCCESS"


def test_missing_cutoff_cannot_produce_successful_job(test_db):
    worker = ResearchWorker(db_path=test_db)
    payload = {
        "match_id": 999,
        "domain": "GENERAL",
        "run_id": "RUN-NO-CUTOFF",
    }
    res = worker.run_execute(payload)
    assert res["status"] == "FAILED"
    assert res["status"] != "SUCCESS"
