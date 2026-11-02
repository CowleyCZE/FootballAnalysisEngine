"""TODO 2.7 – jedno pravidlo bez historie: INSUFFICIENT_DATA => UNRESOLVED, nikdy COMPLETED_WITH_PRIOR."""
import json
import sqlite3
from datetime import datetime, timezone

import pytest

from app.database.schema import initialize_database
from app.orchestrator.orchestrator import MasterOrchestrator
from app.orchestrator.state_machine import MatchState
from app.statistics.engine import StatisticalEngine

CUTOFF = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("FAE_AUTO_HISTORY", "0")
    path = str(tmp_path / "nohist.db")
    initialize_database(path)
    with sqlite3.connect(path) as conn:
        conn.execute("INSERT INTO teams (id, name, normalized_name) VALUES (1, 'Sparta Praha', 'sparta praha'), (2, 'Slavia Praha', 'slavia praha'), (3, 'Zlín', 'zlin')")
        conn.execute("INSERT INTO competitions (id, name) VALUES (1, 'Chance Liga')")
        conn.execute("INSERT INTO matches (id, home_team_id, away_team_id, competition, competition_id, scheduled_at, status) VALUES (1, 1, 2, 'Chance Liga', 1, '2026-11-10T18:00:00+00:00', 'RESOLVED')")
        # Historie má jen domácí tým (Sparta vs Zlín), hosté (Slavia) nic.
        for i in range(2, 8):
            conn.execute(
                "INSERT INTO matches (id, home_team_id, away_team_id, competition, competition_id, scheduled_at, status) VALUES (?, 1, 3, 'Chance Liga', 1, ?, 'RESOLVED')",
                (i, f"2026-10-{i:02d}T15:00:00+00:00"),
            )
            conn.execute("INSERT INTO match_statistics(match_id, home_goals, away_goals) VALUES (?, 2, 1)", (i,))
    return path


def _tick_with_stats(db, result):
    orc = MasterOrchestrator(db_path=db)
    run_id = orc.start_pipeline(1, data_cutoff_at=CUTOFF)
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE jobs SET status='SUCCESS', result_json=? WHERE run_id=? AND job_type='STATISTICS'", (json.dumps(result), run_id))
        conn.execute("UPDATE pipeline_runs SET state='CALCULATING' WHERE run_id=?", (run_id,))
    orc.tick(run_id)
    with sqlite3.connect(db) as conn:
        state = conn.execute("SELECT state FROM pipeline_runs WHERE run_id=?", (run_id,)).fetchone()[0]
        ai_jobs = conn.execute("SELECT COUNT(*) FROM jobs WHERE run_id=? AND job_type='AI_ANALYSIS'", (run_id,)).fetchone()[0]
    return state, ai_jobs


def test_one_sided_history_is_insufficient_data_and_unresolved(db):
    res = StatisticalEngine(db_path=db).run_match_statistics(
        match_id=1, run_id=1, home_team_id=1, away_team_id=2, cutoff_datetime=CUTOFF.isoformat())
    assert res["status"] == "INSUFFICIENT_DATA"
    assert res["sample_size"] > 0  # historie jen jednoho týmu
    state, ai_jobs = _tick_with_stats(db, res)
    assert state == MatchState.UNRESOLVED
    assert ai_jobs == 0


def test_legacy_completed_with_prior_status_is_never_accepted(db):
    legacy = {"status": "COMPLETED_WITH_PRIOR", "sample_size": 6, "prediction": {"factors": {"prior_only": True}}}
    state, ai_jobs = _tick_with_stats(db, legacy)
    assert state == MatchState.UNRESOLVED
    assert ai_jobs == 0


def test_prior_only_prediction_blocks_even_with_completed_status(db):
    result = {"status": "COMPLETED", "sample_size": 6, "prediction": {"factors": {"prior_only": True}}}
    state, _ = _tick_with_stats(db, result)
    assert state == MatchState.UNRESOLVED


def test_full_history_still_passes(db):
    result = {"status": "COMPLETED", "sample_size": 10, "coverage": 0.0, "prediction": {"factors": {"prior_only": False}}}
    state, ai_jobs = _tick_with_stats(db, result)
    assert state == MatchState.ANALYZING
    assert ai_jobs == 1


def test_zero_h2h_and_zero_xg_blocks_do_not_block_valid_prediction(db):
    """Regrese M979 (Artis Brno – Bohemians): nově postoupivší klub nemá H2H (sample_size 0),
    npxG metriky mají vzorek 0, přesto má oba týmy historii a predikce je platná."""
    result = {
        "status": "COMPLETED", "sample_size": 34, "coverage": 0.6,
        "home_team": {"form": {"sample_size": 5}, "xg_aggregate": {"sample_size": 0, "coverage": 0.0},
                      "imported_xg_rates": {"sample_size": 0}, "features": {"npxg_sample_size": 0, "sample_size": 0}},
        "away_team": {"form": {"sample_size": 5}, "xg_aggregate": {"sample_size": 0}},
        "head_to_head": {"sample_size": 0},
        "prediction": {"factors": {"prior_only": False}, "sample_size": 34},
    }
    state, ai_jobs = _tick_with_stats(db, result)
    assert state == MatchState.ANALYZING
    assert ai_jobs == 1


def test_zero_form_sample_still_blocks(db):
    """Nulový vzorek formy (historie) se dál považuje za nedostatečný."""
    result = {
        "status": "COMPLETED", "sample_size": 5,
        "home_team": {"form": {"sample_size": 5}}, "away_team": {"form": {"sample_size": 0}},
        "prediction": {"factors": {"prior_only": False}},
    }
    state, _ = _tick_with_stats(db, result)
    assert state == MatchState.UNRESOLVED
