"""TODO 11.19 – rozšířené ladění (RATING_*), souhrn živých predikcí a doporučení nového ladění."""
import json
import sqlite3

import pytest
import yaml

from app.statistics import backtest
from app.statistics.score_predictor import ExactScorePredictor


@pytest.fixture(autouse=True)
def _reset_params():
    ExactScorePredictor.reset_params()
    yield
    ExactScorePredictor.reset_params()


def _league_rows():
    teams = [1, 2, 3, 4]
    rows, day = [], 1
    for h in teams:
        for a in teams:
            if h != a:
                rows.append({"match_id": day, "home_team_id": h, "away_team_id": a,
                             "home_goals": (h + a) % 4, "away_goals": (h * a) % 3,
                             "scheduled_at": f"2026-01-{day:02d}T18:00:00"})
                day += 1
    return rows


def test_rating_params_are_tunable_and_bounded():
    applied = ExactScorePredictor.apply_params({"RATING_SHRINK": 8.0, "RATING_MIN": 0.5, "RATING_MAX": 1.8})
    assert applied == {"RATING_SHRINK": 8.0, "RATING_MIN": 0.5, "RATING_MAX": 1.8}
    assert ExactScorePredictor.apply_params({"RATING_SHRINK": 99.0, "RATING_MIN": 1.2, "RATING_MAX": 0.5}) == {}
    assert ExactScorePredictor.RATING_SHRINK == 8.0


def test_rating_bounds_change_ratings_and_reset_restores_defaults():
    rows = _league_rows()
    base = ExactScorePredictor.opponent_ratings(rows, 1.3)
    ExactScorePredictor.apply_params({"RATING_SHRINK": 1.0, "RATING_MIN": 0.9, "RATING_MAX": 1.2})
    tight = ExactScorePredictor.opponent_ratings(rows, 1.3)
    assert all(0.9 <= v <= 1.2 for pair in tight.values() for v in pair)
    assert tight != base
    ExactScorePredictor.reset_params()
    assert ExactScorePredictor.opponent_ratings(rows, 1.3) == base
    assert (ExactScorePredictor.RATING_MIN, ExactScorePredictor.RATING_MAX) == ExactScorePredictor.RATING_BOUNDS


def test_refine_extended_keeps_start_when_no_gain(monkeypatch):
    monkeypatch.setattr(backtest, "evaluate", lambda inputs, params=None: {"brier": 0.6})
    start = {"DC_RHO": -0.08}
    result = backtest.refine_extended([], start)
    assert result["DC_RHO"] == -0.08
    assert (result["RATING_SHRINK"], result["RATING_MIN"], result["RATING_MAX"]) == (5.0, 0.6, 1.6)


def test_refine_extended_accepts_only_improving_values(monkeypatch):
    def fake(inputs, params=None):
        params = params or {}
        return {"brier": 0.60 - (0.01 if params.get("RATING_SHRINK") == 8.0 else 0.0)}
    monkeypatch.setattr(backtest, "evaluate", fake)
    result = backtest.refine_extended([], {})
    assert result["RATING_SHRINK"] == 8.0
    assert result["RATING_MIN"] == 0.6 and result["RATING_MAX"] == 1.6


def test_refine_extended_rejects_invalid_bound_combination(monkeypatch):
    monkeypatch.setattr(backtest, "evaluate", lambda inputs, params=None: {"brier": 0.5 if (params or {}).get("RATING_MIN") == 1.2 else 0.6})
    result = backtest.refine_extended([], {}, {"RATING_MIN": (1.2,)})
    assert result["RATING_MIN"] == 0.6


def test_tune_extended_flag_adds_rating_keys(monkeypatch):
    inputs = [{"match_id": i, "scheduled_at": f"2026-01-{i:02d}"} for i in range(1, 11)]
    monkeypatch.setattr(backtest, "evaluate", lambda items, params=None: {"brier": 0.6, "n": len(items)})
    plain = backtest.tune(inputs, grid={"DC_RHO": (-0.08,)}, train_fraction=0.7)
    assert plain["note"].startswith("Příliš málo")  # < 20 zápasů v tréninku – ladění se nespustí
    many = [{"match_id": i, "scheduled_at": f"2026-02-{(i % 27) + 1:02d}-{i:03d}"} for i in range(1, 61)]
    res = backtest.tune(many, grid={"DC_RHO": (-0.08,)}, train_fraction=0.7, extended=True)
    assert res["extended"] is True
    assert {"RATING_SHRINK", "RATING_MIN", "RATING_MAX"} <= set(res["best_params"])
    assert res["recommended"] is False  # žádné zlepšení = výchozí parametry


def test_retune_hint_counts_new_matches(tmp_path):
    cfg = tmp_path / "model_params.yaml"
    assert backtest.retune_hint(600, str(cfg))["recommended"] is False
    cfg.write_text(yaml.safe_dump({"n_train": 369, "n_holdout": 159, "params": {}}), encoding="utf-8")
    assert backtest.retune_hint(560, str(cfg)) == {
        "recommended": False, "tuned_on": 528, "new_matches": 32, "note": "32 nových zápasů od posledního ladnění (limit 50)."}
    assert backtest.retune_hint(578, str(cfg))["recommended"] is True


def test_main_refreshes_retune_hint_after_config_write(tmp_path, monkeypatch, capsys):
    cfg = tmp_path / "model_params.yaml"
    cfg.write_text(yaml.safe_dump({"n_train": 369, "n_holdout": 159, "params": {}}), encoding="utf-8")
    report_path = tmp_path / "report.json"
    inputs = [{"match_id": i} for i in range(609)]
    monkeypatch.setattr(backtest, "build_inputs", lambda *a, **k: inputs)
    monkeypatch.setattr(backtest, "evaluate", lambda items, params=None: {
        "n": len(items), "brier": 0.6, "accuracy_1x2": 0.5, "baseline_accuracy_home_always": 0.46,
        "baseline_brier": 0.64, "brier_skill": 0.06, "exact_score_hit": 0.11, "goals_mae": 0.94})
    monkeypatch.setattr(backtest, "live_feedback_summary", lambda db: {"count": 0})
    monkeypatch.setattr(backtest, "tune", lambda items, extended=False: {
        "n_train": 426, "n_holdout": 183, "recommended": True, "best_params": {"DC_RHO": 0.0},
        "default_holdout": {"brier": 0.61694}, "tuned_holdout": {"brier": 0.61588}})
    rc = backtest.main(["--db", "x.db", "--tune-extended", "--write-config",
                        "--config-path", str(cfg), "--report", str(report_path)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "81 nových zápasů" in out  # doporučení před zápisem (starý config)
    data = json.loads(report_path.read_text(encoding="utf-8"))
    assert data["config_written"] is True
    assert data["retune_hint"] == {"recommended": False, "tuned_on": 609, "new_matches": 0,
                                   "note": "0 nových zápasů od posledního ladnění (limit 50)."}


def test_live_feedback_summary_handles_missing_db(tmp_path):
    assert backtest.live_feedback_summary(str(tmp_path / "missing.db"))["count"] == 0


def test_live_feedback_summary_has_no_match_list(tmp_path):
    db = tmp_path / "x.db"
    with sqlite3.connect(db) as conn:
        conn.executescript("""
            CREATE TABLE teams(id INTEGER PRIMARY KEY, name TEXT);
            CREATE TABLE matches(id INTEGER PRIMARY KEY, scheduled_at TEXT, home_team_id INT, away_team_id INT);
            CREATE TABLE match_statistics(match_id INT, home_goals INT, away_goals INT);
            CREATE TABLE match_predictions(id INTEGER PRIMARY KEY, match_id INT, created_at TEXT, model_version TEXT,
              home_win_probability REAL, draw_probability REAL, away_win_probability REAL,
              expected_home_goals REAL, expected_away_goals REAL, predicted_home_goals INT, predicted_away_goals INT);
            INSERT INTO teams VALUES (1,'A'),(2,'B');
            INSERT INTO matches VALUES (1,'2026-10-20T18:00:00',1,2);
            INSERT INTO match_statistics VALUES (1,2,1);
            INSERT INTO match_predictions VALUES (1,1,'2026-10-19T10:00:00','v7',0.5,0.3,0.2,1.8,0.9,2,1);
        """)
    summary = backtest.live_feedback_summary(str(db))
    assert summary["count"] == 1 and summary["accuracy_1x2"] == 1.0 and "matches" not in summary
    json.dumps(summary)
