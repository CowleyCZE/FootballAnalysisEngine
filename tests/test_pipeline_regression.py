import sqlite3
import json
import pytest
from datetime import datetime, timezone

from app.orchestrator.orchestrator import MasterOrchestrator, MatchOrchestrator
from app.workers.research_worker import ResearchWorker
from app.statistics.engine import StatisticalEngine
from app.database.schema import initialize_database
import menu


@pytest.fixture
def reg_db(tmp_path):
    db_file = str(tmp_path / "regression.db")
    initialize_database(db_file)
    with sqlite3.connect(db_file) as conn:
        conn.execute("INSERT INTO teams (id, name, normalized_name) VALUES (1, 'Sparta Praha', 'sparta praha')")
        conn.execute("INSERT INTO teams (id, name, normalized_name) VALUES (2, 'Slavia Praha', 'slavia praha')")
        conn.execute("INSERT INTO competitions (id, name) VALUES (1, 'Chance Liga')")
        conn.execute("INSERT INTO matches (id, home_team_id, away_team_id, competition, scheduled_at, status) VALUES (1, 1, 2, 'Chance Liga', '2026-11-10T18:00:00+00:00', 'RESOLVED')")
        conn.commit()
    return db_file


def test_reg_1_manual_entry_creates_run_without_match_identity(reg_db):
    orc = MatchOrchestrator(db_path=reg_db)
    from app.orchestrator.models import AnalysisRequest
    req = AnalysisRequest(
        home_team="Sparta Praha",
        away_team="Slavia Praha",
        competition="Chance Liga",
        scheduled_at=datetime(2026, 11, 10, 18, 0, tzinfo=timezone.utc),
    )
    res = orc.start_analysis_run(req)
    assert res["status"] == "DISCOVERY"
    assert res["run_id"] is not None

    with sqlite3.connect(reg_db) as conn:
        match_status = conn.execute("SELECT status FROM matches WHERE id = ?", (res["match_id"],)).fetchone()[0]
        tasks = conn.execute("SELECT domain FROM research_tasks WHERE run_id = ?", (res["run_id"],)).fetchall()
        domains = [t[0] for t in tasks]

    assert match_status == "RESOLVED"
    assert "MATCH_IDENTITY" not in domains


def test_reg_2_stale_run_db_id_resolves_canonical_run_id(reg_db):
    master = MasterOrchestrator(db_path=reg_db)
    run_id = master.start_pipeline(1, data_cutoff_at=datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc))

    with sqlite3.connect(reg_db) as conn:
        task_row = conn.execute("SELECT id, task_uuid, domain FROM research_tasks WHERE run_id = ? AND domain='FORM_HOME'", (run_id,)).fetchone()
        task_id = task_row[0]

    payload = {
        "task_id": task_id,
        "run_id": run_id,
        "run_db_id": 99999,  # Stale / wrong integer
        "match_id": 1,
        "domain": "FORM_HOME",
        "home_team": "Sparta Praha",
        "away_team": "Slavia Praha",
        "competition": "Chance Liga",
        "scheduled_at": "2026-11-10T18:00:00+00:00",
        "data_cutoff_at": "2026-11-01T12:00:00+00:00",
    }

    worker = ResearchWorker(db_path=reg_db)

    class MockEngine:
        def __init__(self, repo):
            self.repository = repo

        def execute(self, task):
            from app.research.research_result import ResearchResult, ResearchMetrics
            from app.research.models import ResearchStatus
            exec_id = self.repository.create_execution("EXEC-STALE-1", task.task_id, task.attempt_number)
            self.repository.create_session("SESS-STALE-1", task.run_id, task.task_id, task.domain)
            self.repository.complete_execution(exec_id, "SUCCESS")
            return ResearchResult(
                task_id=task.task_id,
                execution_id="EXEC-STALE-1",
                status=ResearchStatus.SUCCESS,
                claims=[],
                metrics=ResearchMetrics(),
            )

    worker.engine = MockEngine(worker.repository)
    res = worker.run_execute(payload)

    assert res["status"] == "SUCCESS"
    with sqlite3.connect(reg_db) as conn:
        sess = conn.execute("SELECT run_id, task_id, status FROM research_sessions WHERE task_id = ?", (task_id,)).fetchone()
        real_run_id = conn.execute("SELECT id FROM runs WHERE run_id = ?", (run_id,)).fetchone()[0]

    assert sess is not None
    assert sess[0] == real_run_id
    assert sess[2] in ("RUNNING", "SUCCESS")


def test_reg_3_research_error_closes_task_and_execution_as_failed(reg_db):
    master = MasterOrchestrator(db_path=reg_db)
    run_id = master.start_pipeline(1, data_cutoff_at=datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc))

    with sqlite3.connect(reg_db) as conn:
        task_row = conn.execute("SELECT id FROM research_tasks WHERE run_id = ? AND domain='FORM_HOME'", (run_id,)).fetchone()
        task_id = task_row[0]

    payload = {
        "task_id": task_id,
        "run_id": run_id,
        "match_id": 1,
        "domain": "FORM_HOME",
        "home_team": "Sparta Praha",
        "away_team": "Slavia Praha",
        "competition": "Chance Liga",
        "scheduled_at": "invalid-datetime-trigger-error",
        "data_cutoff_at": "invalid-cutoff",
    }

    worker = ResearchWorker(db_path=reg_db)
    res = worker.run_execute(payload)

    assert res["status"] == "FAILED"
    assert res["error"] is not None

    with sqlite3.connect(reg_db) as conn:
        task_st = conn.execute("SELECT status FROM research_tasks WHERE id = ?", (task_id,)).fetchone()[0]
        exec_st = conn.execute("SELECT status FROM research_executions WHERE task_id = ?", (task_id,)).fetchall()
        sess_st = conn.execute("SELECT status FROM research_sessions WHERE task_id = ?", (task_id,)).fetchall()

    assert task_st == "FAILED"
    for e in exec_st:
        assert e[0] != "RUNNING"
    for s in sess_st:
        assert s[0] != "RUNNING"


def test_reg_4_job_completion_advances_pipeline_from_discovery(reg_db):
    master = MasterOrchestrator(db_path=reg_db)
    run_id = master.start_pipeline(1, data_cutoff_at=datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc))

    with sqlite3.connect(reg_db) as conn:
        state_initial = conn.execute("SELECT state FROM pipeline_runs WHERE run_id = ?", (run_id,)).fetchone()[0]
        conn.execute("UPDATE jobs SET status = 'SUCCESS', result_json = '{\"status\": \"SUCCESS\"}' WHERE run_id = ?", (run_id,))

    assert state_initial == "DISCOVERY"

    master.advance_run(run_id)

    with sqlite3.connect(reg_db) as conn:
        state_after = conn.execute("SELECT state FROM pipeline_runs WHERE run_id = ?", (run_id,)).fetchone()[0]

    assert state_after not in ("DISCOVERY", "NEW")


def test_reg_5_repeated_ticks_do_not_create_duplicate_jobs(reg_db):
    master = MasterOrchestrator(db_path=reg_db)
    run_id = master.start_pipeline(1, data_cutoff_at=datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc))

    with sqlite3.connect(reg_db) as conn:
        conn.execute("UPDATE jobs SET status = 'SUCCESS', result_json = '{\"status\": \"COMPLETED\", \"sample_size\": 5, \"coverage\": 1.0}' WHERE run_id = ?", (run_id,))
        conn.execute("UPDATE pipeline_runs SET state = 'CALCULATING' WHERE run_id = ?", (run_id,))

    master.tick(run_id)
    with sqlite3.connect(reg_db) as conn:
        ai_jobs_count_1 = conn.execute("SELECT COUNT(*) FROM jobs WHERE run_id = ? AND job_type = 'AI_ANALYSIS'", (run_id,)).fetchone()[0]

    master.tick(run_id)
    master.tick(run_id)

    with sqlite3.connect(reg_db) as conn:
        ai_jobs_count_2 = conn.execute("SELECT COUNT(*) FROM jobs WHERE run_id = ? AND job_type = 'AI_ANALYSIS'", (run_id,)).fetchone()[0]

    assert ai_jobs_count_1 == 1
    assert ai_jobs_count_2 == 1


def test_reg_6_zero_stats_not_presented_as_usable(reg_db):
    engine = StatisticalEngine(db_path=reg_db)
    res = engine.run_match_statistics(
        match_id=1,
        run_id=1,
        home_team_id=1,
        away_team_id=2,
        cutoff_datetime="2026-11-01T12:00:00+00:00",
    )
    assert res["status"] == "INSUFFICIENT_DATA"
    assert res["sample_size"] == 0

    master = MasterOrchestrator(db_path=reg_db)
    run_id = master.start_pipeline(1, data_cutoff_at=datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc))

    with sqlite3.connect(reg_db) as conn:
        conn.execute("UPDATE jobs SET status = 'SUCCESS', result_json = ? WHERE run_id = ? AND job_type = 'STATISTICS'", (json.dumps(res), run_id))
        conn.execute("UPDATE pipeline_runs SET state = 'CALCULATING' WHERE run_id = ?", (run_id,))

    master.tick(run_id)

    with sqlite3.connect(reg_db) as conn:
        state = conn.execute("SELECT state FROM pipeline_runs WHERE run_id = ?", (run_id,)).fetchone()[0]

    assert state == "UNRESOLVED"


def test_reg_7_menu_displays_snapshots(tmp_path, monkeypatch, capsys):
    db_path = tmp_path / "menu_snapshots.db"
    initialize_database(str(db_path))
    monkeypatch.setattr(menu, "DB_PATH", str(db_path))

    with sqlite3.connect(db_path) as conn:
        conn.execute("INSERT INTO teams (id, name, normalized_name) VALUES (1, 'Sparta Praha', 'sparta praha')")
        conn.execute("INSERT INTO teams (id, name, normalized_name) VALUES (2, 'Slavia Praha', 'slavia praha')")
        conn.execute("INSERT INTO competitions (id, name) VALUES (1, 'Chance Liga')")
        conn.execute("INSERT INTO matches (id, home_team_id, away_team_id, competition, scheduled_at, status) VALUES (1, 1, 2, 'Chance Liga', '2026-11-10T18:00:00Z', 'RESOLVED')")
        conn.execute("INSERT INTO runs (id, run_id, status, started_at) VALUES (1, 'RUN-SNAP-1', 'RUNNING', '2026-11-01T10:00:00Z')")
        conn.execute("INSERT INTO pipeline_runs (run_id, match_id, state, cycle, max_cycles, started_at, updated_at) VALUES ('RUN-SNAP-1', 1, 'CALCULATING', 1, 3, '2026-11-01T10:00:00Z', '2026-11-01T10:00:00Z')")
        conn.execute("""
            INSERT INTO statistical_snapshots (run_id, match_id, team_id, metric, value, sample_size, coverage, data_cutoff_at, calculation_version)
            VALUES (1, 1, 1, 'form_points', 9.0, 5, 1.0, '2026-11-01T12:00:00Z', '1.0.0')
        """)

    monkeypatch.setattr("builtins.input", lambda _prompt="": "1")
    menu.show_analysis_results()
    output = capsys.readouterr().out

    assert "Sparta Praha" in output
    assert "form_points" in output
    assert "9.00" in output
    assert "100%" in output
