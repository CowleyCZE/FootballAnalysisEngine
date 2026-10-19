import json
import sqlite3
from datetime import datetime, timezone

import menu
from app.database.schema import initialize_database


def setup_db(tmp_path, monkeypatch):
    db_path = tmp_path / "menu-test.db"
    initialize_database(str(db_path))
    monkeypatch.setattr(menu, "DB_PATH", str(db_path))
    return db_path


def add_match_fixture(conn, status="RESOLVED"):
    conn.execute(
        "INSERT INTO teams(id, name, normalized_name) VALUES (1, 'Sparta Praha', 'sparta praha'), (2, 'Slavia Praha', 'slavia praha')"
    )
    conn.execute("INSERT INTO competitions(id, name) VALUES (1, 'Chance Liga')")
    conn.execute(
        "INSERT INTO matches(id, competition, competition_id, home_team_id, away_team_id, scheduled_at, status) "
        "VALUES (1, 'Chance Liga', 1, 1, 2, '2026-11-10T18:00:00+00:00', ?)",
        (status,),
    )


def test_add_match_saves_user_input_as_resolved(tmp_path, monkeypatch):
    db_path = setup_db(tmp_path, monkeypatch)
    answers = iter(("Sparta Praha", "Slavia Praha", "Chance Liga", "10.11.2026 19:00", ""))
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))
    captured = {}

    class FakeOrchestrator:
        def __init__(self, db_path):
            pass

        def start_pipeline(self, match_id, data_cutoff_at=None):
            captured.update(match_id=match_id, cutoff=data_cutoff_at)
            return "RUN-MANUAL-1"

    monkeypatch.setattr(menu, "MasterOrchestrator", FakeOrchestrator)

    menu.add_match()

    with sqlite3.connect(db_path) as conn:
        row = conn.execute("SELECT status FROM matches").fetchone()
    assert row == ("RESOLVED",)
    assert captured["match_id"] == 1
    assert isinstance(captured["cutoff"], datetime)


def test_get_or_create_competition_matches_unicode_case_insensitively(tmp_path, monkeypatch):
    db_path = setup_db(tmp_path, monkeypatch)
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        existing_id = menu.get_or_create_competition(cursor, "Česká Chance Liga")
        same_id = menu.get_or_create_competition(cursor, "česká chance liga")
        count = cursor.execute("SELECT COUNT(*) FROM competitions").fetchone()[0]

    assert same_id == existing_id
    assert count == 1


def test_run_analysis_passes_cutoff_to_orchestrator(tmp_path, monkeypatch):
    db_path = setup_db(tmp_path, monkeypatch)
    with sqlite3.connect(db_path) as conn:
        add_match_fixture(conn)

    captured = {}

    class FakeOrchestrator:
        def __init__(self, db_path):
            assert db_path == str(db_path_arg)

        def start_pipeline(self, match_id, data_cutoff_at=None):
            captured["match_id"] = match_id
            captured["cutoff"] = data_cutoff_at
            return "RUN-1"

    db_path_arg = db_path
    monkeypatch.setattr(menu, "MasterOrchestrator", FakeOrchestrator)
    answers = iter(("1", ""))
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))

    menu.run_analysis()

    assert captured["match_id"] == 1
    assert isinstance(captured["cutoff"], datetime)
    assert captured["cutoff"].tzinfo == timezone.utc


def test_print_matches_handles_missing_joined_team_names(capsys):
    # A legacy or partially populated match can have NULL/missing team names;
    # the menu should display placeholders instead of crashing on width format.
    row = {
        "id": 5,
        "home_team": None,
        "away_team": "Slavia Praha",
        "competition": "Chance Liga",
        "scheduled_at": "2026-10-17 22:00:00+00:00",
        "status": "UNVERIFIED",
    }

    menu.print_matches([row])

    output = capsys.readouterr().out
    assert "5" in output
    assert "?" in output
    assert "Slavia Praha" in output
    assert "UNVERIFIED" in output


def test_show_results_reads_ai_and_audit_from_selected_run(tmp_path, monkeypatch, capsys):
    db_path = setup_db(tmp_path, monkeypatch)
    with sqlite3.connect(db_path) as conn:
        add_match_fixture(conn)
        conn.execute(
            "INSERT INTO runs(id, run_id, status, started_at) VALUES (1, 'RUN-1', 'RUNNING', '2026-11-01T10:00:00Z')"
        )
        conn.execute(
            "INSERT INTO pipeline_runs(run_id, match_id, state, cycle, max_cycles, started_at, updated_at) "
            "VALUES ('RUN-1', 1, 'COMPLETED', 1, 3, '2026-11-01T10:00:00Z', '2026-11-01T10:01:00Z')"
        )
        conn.execute(
            "INSERT INTO jobs(job_id, run_id, match_id, job_type, status, result_json) VALUES (?, ?, ?, ?, ?, ?)",
            ("AI-1", "RUN-1", 1, "AI_ANALYSIS", "SUCCESS", json.dumps({"status": "complete", "conclusion": "Výsledek aktuálního běhu"}, ensure_ascii=False)),
        )
        conn.execute(
            "INSERT INTO jobs(job_id, run_id, match_id, job_type, status, result_json) VALUES (?, ?, ?, ?, ?, ?)",
            ("AUDIT-1", "RUN-1", 1, "AUDIT", "SUCCESS", json.dumps({"status": "AUDIT_COMPLETE", "audit_score": 0.9, "issues": []})),
        )
        conn.execute(
            "INSERT INTO claims(run_id, match_id, claim_text, status, confidence) VALUES (1, 1, 'Claim aktuálního běhu', 'VALID', 0.9)"
        )

    monkeypatch.setattr("builtins.input", lambda _prompt="": "1")
    menu.show_analysis_results()
    output = capsys.readouterr().out

    assert "Výsledek aktuálního běhu" in output
    assert "AUDIT_COMPLETE" in output
    assert "Claim aktuálního běhu" in output
