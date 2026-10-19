import sqlite3

import pytest

from app.database.research_repository import ResearchRepository


def _prepare_db(path: str) -> ResearchRepository:
    repo = ResearchRepository(path)
    with sqlite3.connect(path) as conn:
        conn.execute("INSERT INTO runs(id, run_id, status, started_at) VALUES (1, 'RUN-1', 'RUNNING', '2026-10-04T10:00:00Z')")
        conn.execute("INSERT INTO teams(id, name, normalized_name) VALUES (1, 'Arsenal', 'arsenal')")
        conn.execute("INSERT INTO teams(id, name, normalized_name) VALUES (2, 'Chelsea', 'chelsea')")
        conn.execute("INSERT INTO matches(id, competition, home_team_id, away_team_id, scheduled_at) VALUES (10, 'Premier League', 1, 2, '2026-10-04T15:00:00Z')")
        conn.execute("""INSERT INTO research_tasks(
            id, run_id, run_db_id, match_id, task_uuid, domain, task_type, description,
            required, priority, capabilities_json, data_cutoff_at, home_team, away_team,
            competition, scheduled_at, status, attempt_number
        ) VALUES (1, 'RUN-1', 1, 10, 'TASK-1', 'ABSENCES_HOME', 'NEWS_COLLECTION', 'test',
                  1, 90, '[\"http_fetch\"]', '2026-10-04T12:00:00Z', 'Arsenal', 'Chelsea',
                  'Premier League', '2026-10-04T15:00:00Z', 'QUEUED', 1)""")
    return repo


def test_research_task_transitions_running_and_terminal(tmp_path):
    repo = _prepare_db(str(tmp_path / "research.db"))
    repo.mark_task_running(1, 2)
    execution_id = repo.create_execution("EXEC-1", 1, 2)
    with sqlite3.connect(repo.db_path) as conn:
        status, attempt = conn.execute("SELECT status, attempt_number FROM research_tasks WHERE id=1").fetchone()
    assert status == "RUNNING"
    assert attempt == 2

    repo.complete_execution(execution_id, "CONFLICTED", "two sources disagree")
    with sqlite3.connect(repo.db_path) as conn:
        task_status = conn.execute("SELECT status FROM research_tasks WHERE id=1").fetchone()[0]
        execution_status = conn.execute("SELECT status FROM research_executions WHERE id=?", (execution_id,)).fetchone()[0]
    assert task_status == "CONFLICTED"
    assert execution_status == "CONFLICTED"


def test_terminal_task_cannot_be_started_again(tmp_path):
    repo = _prepare_db(str(tmp_path / "research.db"))
    repo.mark_task_running(1, 1)
    execution_id = repo.create_execution("EXEC-1", 1, 1)
    repo.complete_execution(execution_id, "SUCCESS")
    with pytest.raises(RuntimeError):
        repo.mark_task_running(1, 2)
