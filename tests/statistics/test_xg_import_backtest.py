import random
import sqlite3
from datetime import datetime, timedelta

import pytest

from app.database.schema import initialize_database
from app.statistics import backtest
from app.statistics.score_predictor import ExactScorePredictor
from app.statistics.xg_import import import_xg_rows, parse_csv


@pytest.fixture(autouse=True)
def _reset_model_params():
    ExactScorePredictor.reset_params()
    yield
    ExactScorePredictor.reset_params()


def _db(tmp_path):
    path = str(tmp_path / "t.db")
    initialize_database(path)
    return path


def _add_team(conn, name):
    return conn.execute("INSERT INTO teams(name, normalized_name) VALUES(?, ?)", (name, name.lower())).lastrowid


def _add_match(conn, home, away, when, hg=None, ag=None, competition="TestLiga"):
    mid = conn.execute(
        "INSERT INTO matches(competition, home_team_id, away_team_id, scheduled_at) VALUES(?,?,?,?)",
        (competition, home, away, when),
    ).lastrowid
    if hg is not None:
        conn.execute("INSERT INTO match_statistics(match_id, home_goals, away_goals) VALUES(?,?,?)", (mid, hg, ag))
    return mid


# --- xG import --------------------------------------------------------------------------------

def test_parse_csv_flags_invalid_rows_and_semicolons():
    text = "date;home_team;away_team;home_xg;away_xg\n2026-10-17;A;B;1,5;0.9\n2026-10-18;A;B;abc;1\n17.13.2026;A;B;1;1\n"
    rows = parse_csv(text)
    assert rows[0]["home_xg"] == 1.5 and "error" not in rows[0]
    assert rows[1]["error"].startswith("neplatné xG")
    assert rows[2]["error"] == "neplatné datum"


def test_parse_csv_missing_columns():
    with pytest.raises(ValueError):
        parse_csv("date,home_team\n2026-10-17,A\n")


def test_xg_out_of_range_is_invalid():
    rows = parse_csv("date,home_team,away_team,home_xg,away_xg\n2026-10-17,A,B,9.5,1\n")
    assert "error" in rows[0]


def test_xg_import_updates_existing_match_only(tmp_path):
    db = _db(tmp_path)
    with sqlite3.connect(db) as conn:
        a, b = _add_team(conn, "Alfa Praha"), _add_team(conn, "Beta Brno")
        done = _add_match(conn, a, b, "2026-10-17T15:00:00+00:00", 2, 1)
        _add_match(conn, b, a, "2026-10-30T15:00:00+00:00")  # budoucí zápas bez výsledku
    rows = parse_csv(
        "date,home_team,away_team,home_xg,away_xg\n"
        "2026-10-17,Alfa Praha,Beta Brno,1.84,0.92\n"
        "2026-10-30,Beta Brno,Alfa Praha,1.0,1.0\n"
        "2026-10-20,Alfa Praha,Neznámý,1.0,1.0\n"
    )
    res = import_xg_rows(rows, db, source="testsrc")
    assert res["updated"] == 1 and res["unmatched"] == 2
    with sqlite3.connect(db) as conn:
        hx, ax, hxga, axga, definition = conn.execute(
            "SELECT home_xg, away_xg, home_xga, away_xga, xg_metric_definition FROM match_statistics WHERE match_id=?",
            (done,)).fetchone()
    assert (hx, ax, hxga, axga, definition) == (1.84, 0.92, 0.92, 1.84, "testsrc")


def test_xg_import_day_tolerance_and_dry_run(tmp_path):
    db = _db(tmp_path)
    with sqlite3.connect(db) as conn:
        a, b = _add_team(conn, "Alfa Praha"), _add_team(conn, "Beta Brno")
        mid = _add_match(conn, a, b, "2026-10-17T22:30:00+00:00", 0, 0)
    rows = parse_csv("date,home_team,away_team,home_xg,away_xg\n2026-10-18,Alfa Praha,Beta Brno,0.5,0.4\n")
    dry = import_xg_rows(rows, db, source="s", dry_run=True)
    assert dry["updated"] == 1
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT home_xg FROM match_statistics WHERE match_id=?", (mid,)).fetchone()[0] is None
    import_xg_rows(rows, db, source="s")
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT home_xg FROM match_statistics WHERE match_id=?", (mid,)).fetchone()[0] == 0.5


def test_xg_from_other_source_is_not_overwritten_without_flag(tmp_path):
    db = _db(tmp_path)
    with sqlite3.connect(db) as conn:
        a, b = _add_team(conn, "Alfa Praha"), _add_team(conn, "Beta Brno")
        mid = _add_match(conn, a, b, "2026-10-17T15:00:00+00:00", 1, 1)
    rows = parse_csv("date,home_team,away_team,home_xg,away_xg\n2026-10-17,Alfa Praha,Beta Brno,1.0,1.0\n")
    import_xg_rows(rows, db, source="first")
    rows2 = parse_csv("date,home_team,away_team,home_xg,away_xg\n2026-10-17,Alfa Praha,Beta Brno,2.0,2.0\n")
    assert import_xg_rows(rows2, db, source="second")["skipped_existing"] == 1
    assert import_xg_rows(rows2, db, source="second", overwrite=True)["updated"] == 1
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT home_xg FROM match_statistics WHERE match_id=?", (mid,)).fetchone()[0] == 2.0


# --- Backtest ---------------------------------------------------------------------------------

def test_outcome_and_score_one():
    assert [backtest.outcome_index(2, 1), backtest.outcome_index(1, 1), backtest.outcome_index(0, 3)] == [0, 1, 2]
    pred = {"home_win_probability": 0.6, "draw_probability": 0.25, "away_win_probability": 0.15,
            "predicted_home_goals": 2, "predicted_away_goals": 1,
            "expected_home_goals": 1.8, "expected_away_goals": 0.9}
    s = backtest.score_one(pred, 2, 1)
    assert s["correct"] == 1.0 and s["exact"] == 1.0
    assert s["brier"] == pytest.approx(0.16 + 0.0625 + 0.0225)
    assert backtest.score_one(pred, 0, 2)["correct"] == 0.0


def test_summarize_baseline_and_empty():
    assert backtest.summarize([]) == {"n": 0}
    items = [{"outcome": 0, "correct": 1.0, "brier": 0.2, "log_loss": 0.5, "exact": 0.0, "goals_abs_error": 1.0},
             {"outcome": 2, "correct": 0.0, "brier": 0.8, "log_loss": 1.5, "exact": 0.0, "goals_abs_error": 2.0}]
    s = backtest.summarize(items)
    assert s["n"] == 2 and s["accuracy_1x2"] == 0.5 and s["brier"] == 0.5
    assert s["baseline_brier"] == pytest.approx(0.5)


def test_apply_params_bounds_and_reset():
    P = ExactScorePredictor
    applied = P.apply_params({"HOME_ADV_SPLIT": 1.10, "DC_RHO": 5.0, "UNKNOWN": 1, "FORM_DECAY": "x"})
    assert applied == {"HOME_ADV_SPLIT": 1.10}
    assert P.HOME_ADV_SPLIT == 1.10 and P.DC_RHO == -0.08
    P.reset_params()
    assert P.HOME_ADV_SPLIT == 1.03 and P._TUNED == {}


def _league(db):
    rng = random.Random(7)
    strength = {0: 1.6, 1: 1.3, 2: 1.1, 3: 1.0, 4: 0.8, 5: 0.6}
    start = datetime(2026, 1, 1, 15, 0)
    with sqlite3.connect(db) as conn:
        ids = [_add_team(conn, f"Tým {i}") for i in range(6)]
        day = 0
        for rnd in range(14):
            for i in range(6):
                j = (i + 1 + rnd) % 6
                if i == j:
                    continue
                lam_h = 1.25 * strength[i] / strength[j] ** 0.5
                lam_a = 1.0 * strength[j] / strength[i] ** 0.5
                hg = sum(1 for _ in range(6) if rng.random() < lam_h / 6)
                ag = sum(1 for _ in range(6) if rng.random() < lam_a / 6)
                when = (start + timedelta(days=day)).strftime("%Y-%m-%dT%H:%M:%S+00:00")
                _add_match(conn, ids[i], ids[j], when, hg, ag)
                day += 1
    return db


def test_build_inputs_has_no_future_data_and_evaluate_restores_params(tmp_path):
    db = _league(_db(tmp_path))
    inputs = backtest.build_inputs(db, "TestLiga", min_history=5)
    assert len(inputs) > 20
    for inp in inputs:
        assert all(r["scheduled_at"] < inp["scheduled_at"] for r in inp["rows"])
        assert all(r["match_id"] != inp["match_id"] for r in inp["rows"])
    summary = backtest.evaluate(inputs)
    assert summary["n"] == len(inputs) and 0.0 < summary["brier"] < 2.0
    backtest.evaluate(inputs, {"HOME_ADV_SPLIT": 1.10})
    assert ExactScorePredictor.HOME_ADV_SPLIT == 1.03


def test_tune_returns_split_and_never_recommends_without_holdout_gain(tmp_path):
    db = _league(_db(tmp_path))
    inputs = backtest.build_inputs(db, "TestLiga", min_history=5)
    result = backtest.tune(inputs, grid={"DC_RHO": (-0.08, 0.0), "HOME_ADV_NO_SPLIT": (1.04, 1.08)})
    assert result["n_train"] + result["n_holdout"] == len(inputs)
    assert result["best_params"] is not None
    if result["recommended"]:
        assert result["holdout_brier_gain"] >= backtest.MIN_IMPROVEMENT
    assert ExactScorePredictor.DC_RHO == -0.08


def test_write_config_only_when_recommended(tmp_path):
    path = str(tmp_path / "model_params.yaml")
    assert backtest.write_config(path, {"recommended": False}, "X") is False
    tuning = {"recommended": True, "best_params": {"HOME_ADV_SPLIT": 1.06}, "n_train": 70, "n_holdout": 30,
              "default_holdout": {"brier": 0.6}, "tuned_holdout": {"brier": 0.59}}
    assert backtest.write_config(path, tuning, "X") is True
    from app.statistics.score_predictor import load_tuned_params
    assert load_tuned_params(path) == {"HOME_ADV_SPLIT": 1.06}
    assert ExactScorePredictor.HOME_ADV_SPLIT == 1.06
