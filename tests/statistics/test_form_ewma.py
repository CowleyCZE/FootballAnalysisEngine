from __future__ import annotations

from app.statistics.form import FormEngine


def _match(date, home, away, hg, ag, hx=None, ax=None):
    return {
        "scheduled_at": date,
        "home_team_id": home,
        "away_team_id": away,
        "home_goals": hg,
        "away_goals": ag,
        "home_xg": hx,
        "away_xg": ax,
    }


def test_ewma_weights_recent_matches_higher():
    # Team 1 lost early, then won recently -> recent wins should dominate EWMA.
    rows = [
        _match("2025-08-01", 1, 2, 0, 3, 0.4, 2.5),
        _match("2025-08-08", 1, 3, 0, 2, 0.5, 2.0),
        _match("2025-08-15", 1, 4, 2, 0, 2.1, 0.5),
        _match("2025-08-22", 1, 5, 3, 0, 2.6, 0.4),
    ]
    form = FormEngine.calculate_ewma_form(rows, 1)
    assert form["sample_size"] == 4
    assert form["xg_sample_size"] == 4
    assert form["gd_ewma"] > 0
    assert form["xgd_ewma"] > 0
    assert form["form_score"] > 0


def test_venue_split_activates_with_enough_matches():
    rows = [
        _match("2025-08-01", 1, 2, 2, 0, 2.0, 0.6),
        _match("2025-08-08", 1, 3, 2, 0, 1.9, 0.5),
        _match("2025-08-15", 1, 4, 3, 1, 2.4, 0.7),
        _match("2025-08-22", 5, 1, 3, 0, 2.5, 0.3),
    ]
    home_form = FormEngine.calculate_ewma_form(rows, 1, venue="home")
    away_form = FormEngine.calculate_ewma_form(rows, 1, venue="away")
    assert home_form["venue_split_used"] is True
    assert away_form["venue_split_used"] is False
    assert home_form["form_score"] > away_form["form_score"]


def test_opponent_strength_normalizes_form():
    rows = [_match("2025-08-01", 1, 2, 2, 0, 2.0, 0.5)]
    weak_opp = {2: (0.7, 1.4)}
    strong_opp = {2: (1.4, 0.7)}
    vs_weak = FormEngine.calculate_ewma_form(rows, 1, ratings=weak_opp)
    vs_strong = FormEngine.calculate_ewma_form(rows, 1, ratings=strong_opp)
    assert vs_strong["xgd_ewma"] > vs_weak["xgd_ewma"]
    assert vs_strong["avg_opponent_strength"] > vs_weak["avg_opponent_strength"]


def test_missing_xg_is_not_fabricated():
    rows = [_match("2025-08-01", 1, 2, 2, 1, None, None)]
    form = FormEngine.calculate_ewma_form(rows, 1)
    assert form["xgd_ewma"] is None
    assert form["xg_sample_size"] == 0
    assert form["gd_ewma"] == 1.0
