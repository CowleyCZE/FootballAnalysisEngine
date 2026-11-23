from __future__ import annotations

from app.statistics.calibration import PlattCalibrator
from app.statistics.score_predictor import ExactScorePredictor


def _sample_rows():
    return [
        {"scheduled_at": "2025-08-01", "home_team_id": 1, "away_team_id": 2, "home_goals": 2, "away_goals": 0, "home_xg": 2.1, "away_xg": 0.5, "home_xga": 0.5, "away_xga": 2.1},
        {"scheduled_at": "2025-08-08", "home_team_id": 1, "away_team_id": 3, "home_goals": 3, "away_goals": 1, "home_xg": 2.4, "away_xg": 0.8, "home_xga": 0.8, "away_xga": 2.4},
        {"scheduled_at": "2025-08-15", "home_team_id": 2, "away_team_id": 3, "home_goals": 1, "away_goals": 1, "home_xg": 1.0, "away_xg": 1.1, "home_xga": 1.1, "away_xga": 1.0},
        {"scheduled_at": "2025-08-22", "home_team_id": 3, "away_team_id": 1, "home_goals": 0, "away_goals": 2, "home_xg": 0.6, "away_xg": 1.9, "home_xga": 1.9, "away_xga": 0.6},
        {"scheduled_at": "2025-08-29", "home_team_id": 2, "away_team_id": 1, "home_goals": 0, "away_goals": 1, "home_xg": 0.7, "away_xg": 1.6, "home_xga": 1.6, "away_xga": 0.7},
    ]


def test_predict_uses_xg_ratings_and_ewma_form():
    rows = _sample_rows()
    result = ExactScorePredictor.predict(rows, 1, 2, league_rows=rows)
    assert result is not None
    assert result["factors"]["xg_ratings_used"] is True
    assert result["factors"]["ewma_form"]["home"]["sample_size"] == 4
    assert result["factors"]["ewma_form"]["away"]["sample_size"] == 3
    assert result["home_win_probability"] > result["away_win_probability"]


def test_predict_draw_inflation_increases_draw_probability():
    rows = _sample_rows()
    base = ExactScorePredictor.predict(rows, 1, 2, league_rows=rows, params={"DRAW_INFLATION": 1.0})
    inflated = ExactScorePredictor.predict(rows, 1, 2, league_rows=rows, params={"DRAW_INFLATION": 1.25})
    assert inflated["draw_probability"] > base["draw_probability"]
    assert inflated["factors"]["draw_inflation"] == 1.25


def test_predict_applies_platt_calibrator():
    rows = _sample_rows()
    cal = PlattCalibrator({"home": (0.8, 0.0), "draw": (1.0, 0.3), "away": (0.8, 0.0)})
    result = ExactScorePredictor.predict(rows, 1, 2, league_rows=rows, calibrator=cal)
    assert result["factors"]["calibrated"] is True
    assert "raw_1x2_probabilities" in result["factors"]
    total = result["home_win_probability"] + result["draw_probability"] + result["away_win_probability"]
    assert abs(total - 1.0) < 1e-4
