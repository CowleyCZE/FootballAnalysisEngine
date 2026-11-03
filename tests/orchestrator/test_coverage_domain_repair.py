"""Běh M979_3ef7: povinná TEAM_PROFILE_HOME skončila NO_RESULT a opravný task GENERAL ji nemohl doplnit
→ 3 cykly a UNRESOLVED. Opravný task téže domény nyní dřívější selhání nahradí."""
import sqlite3
from datetime import datetime, timezone

import pytest

from app.database.schema import initialize_database
from app.orchestrator.coverage import CoverageEngine
from app.orchestrator.models import MatchIdentity
from app.orchestrator.orchestrator import MasterOrchestrator


@pytest.fixture
def db(tmp_path):
    path = str(tmp_path / "repair.db")
    initialize_database(path)
    with sqlite3.connect(path) as conn:
        conn.execute("INSERT INTO teams (id, name, normalized_name) VALUES (1, 'SK Artis Brno', 'artis brno')")
        conn.execute("INSERT INTO teams (id, name, normalized_name) VALUES (2, 'Bohemians 1905', 'bohemians 1905')")
        conn.execute("INSERT INTO matches (id, home_team_id, away_team_id, competition, scheduled_at, status) "
                     "VALUES (10, 1, 2, 'Chance Liga', '2026-11-04T17:00:00+00:00', 'RESOLVED')")
        conn.execute("INSERT INTO runs(id, run_id, status, started_at) VALUES (1, 'R1', 'RUNNING', '2026-11-02T10:00:00Z')")
    return path


def _task(path, idx, domain, status, required=1):
    with sqlite3.connect(path) as conn:
        conn.execute(
            "INSERT INTO research_tasks(id, run_id, run_db_id, match_id, task_uuid, domain, task_type, description, "
            "required, priority, capabilities_json, data_cutoff_at, home_team, away_team, competition, scheduled_at, status) "
            "VALUES (?, 'R1', 1, 10, ?, ?, 'NEWS_COLLECTION', 't', ?, 50, '[]', '2026-11-02T12:00:00Z', 'SK Artis Brno', "
            "'Bohemians 1905', 'Chance Liga', '2026-11-04T17:00:00Z', ?)",
            (idx, f"U{idx}", domain, required, status))


def test_missing_domains_are_reported(db):
    _task(db, 1, "TEAM_PROFILE_HOME", "NO_RESULT")
    _task(db, 2, "TEAM_PROFILE_AWAY", "SUCCESS")
    ready = CoverageEngine(db).evaluate_run("R1", 1)
    assert not ready.ready
    assert ready.missing_domains == ["TEAM_PROFILE_HOME"]


def test_successful_repair_task_supersedes_earlier_no_result(db):
    _task(db, 1, "TEAM_PROFILE_HOME", "NO_RESULT")
    _task(db, 2, "TEAM_PROFILE_AWAY", "SUCCESS")
    _task(db, 3, "TEAM_PROFILE_HOME", "SUCCESS", required=0)  # opravný task
    ready = CoverageEngine(db).evaluate_run("R1", 1)
    assert ready.ready
    assert ready.missing_domains == []


def test_failed_repair_task_keeps_blocking(db):
    _task(db, 1, "TEAM_PROFILE_HOME", "NO_RESULT")
    _task(db, 2, "TEAM_PROFILE_HOME", "NO_RESULT", required=0)
    assert not CoverageEngine(db).evaluate_run("R1", 1).ready


def test_coverage_repair_tasks_rerun_missing_domains_with_subject_team():
    ident = MatchIdentity(match_id=10, home_team_id=1, away_team_id=2, home_team="SK Artis Brno",
                          away_team="Bohemians 1905", competition="Chance Liga",
                          scheduled_at=datetime(2026, 11, 4, 17, tzinfo=timezone.utc))
    tasks = MasterOrchestrator._coverage_repair_tasks(
        "RUN", 1, "Chybí TEAM_PROFILE_HOME", ["TEAM_PROFILE_HOME", "TEAM_PROFILE_AWAY", "STATISTICS"], ident)
    by_domain = {t.domain: t for t in tasks}
    assert set(by_domain) == {"TEAM_PROFILE_HOME", "TEAM_PROFILE_AWAY", "GENERAL"}
    assert by_domain["TEAM_PROFILE_HOME"].subject_team_id == 1
    assert by_domain["TEAM_PROFILE_AWAY"].subject_team_id == 2
    assert by_domain["TEAM_PROFILE_HOME"].task_type == "NEWS_COLLECTION"
    assert all(t.task_uuid.startswith("REPAIR-COVERAGE-RUN-1-") for t in tasks)
    assert not any(t.required for t in tasks)


def test_search_diagnostics_list_dropped_samples():
    from app.search.models import SearchDiagnostics
    diag = SearchDiagnostics(query="q", raw_count=10, normalized_count=10, dedup_count=10, sport_filtered_count=10,
                             cutoff_filtered_count=10, final_count=0,
                             identity_dropped_samples=["Titulek <https://example.org/a>"])
    assert any("Příklady vyřazených" in r and "example.org" in r for r in diag.drop_reasons)
