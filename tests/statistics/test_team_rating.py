from __future__ import annotations

from app.statistics.team_rating import compute_xg_team_ratings, filter_matches_before


def _row(match_id, home, away, date, hx, ax, hxga, axga):
    return {
        "id": match_id,
        "home_team_id": home,
        "away_team_id": away,
        "scheduled_at": date,
        "home_goals": 1,
        "away_goals": 1,
        "home_xg": hx,
        "away_xg": ax,
        "home_xga": hxga,
        "away_xga": axga,
    }


def test_ratings_are_deterministic_and_opponent_adjusted():
    rows = [
        _row(1, 1, 2, "2025-08-10", 2.0, 0.5, 0.5, 2.0),
        _row(2, 2, 1, "2025-08-17", 0.4, 1.8, 1.8, 0.4),
        _row(3, 1, 3, "2025-08-24", 1.8, 0.7, 0.7, 1.8),
        _row(4, 3, 2, "2025-08-31", 0.8, 0.8, 0.8, 0.8),
    ]
    first = compute_xg_team_ratings(rows, 1.25)
    second = compute_xg_team_ratings(rows, 1.25)
    assert first == second
    assert first[1][0] > first[2][0]
    assert first[1][1] < first[2][1]


def test_small_sample_shrinks_toward_league_average():
    rows = [_row(1, 1, 2, "2025-08-10", 4.0, 0.1, 0.1, 4.0)]
    ratings = compute_xg_team_ratings(rows, 1.25, shrink=5.0)
    attack, defence = ratings[1]
    assert 1.0 < attack < 1.6
    assert 0.6 < defence < 1.0


def test_rows_without_complete_xg_are_ignored():
    rows = [
        _row(1, 1, 2, "2025-08-10", 1.5, 1.0, 1.0, 1.5),
        _row(2, 1, 3, "2025-08-17", 2.0, None, 1.0, 1.0),
    ]
    ratings = compute_xg_team_ratings(rows, 1.25)
    assert set(ratings) == {1, 2}


def test_cutoff_excludes_future_matches():
    rows = [
        _row(1, 1, 2, "2025-08-10", 2.0, 0.5, 0.5, 2.0),
        _row(2, 1, 3, "2025-09-10", 5.0, 0.1, 0.1, 5.0),
    ]
    historical = filter_matches_before(rows, "2025-09-01")
    ratings = compute_xg_team_ratings(historical, 1.25)
    assert set(ratings) == {1, 2}
    assert ratings[1][0] < 1.6


def test_empty_or_invalid_input_returns_empty_mapping():
    assert compute_xg_team_ratings([], 1.25) == {}
    assert compute_xg_team_ratings([_row(1, 1, 2, "2025-08-10", None, 1.0, 1.0, 1.0)], 1.25) == {}
    assert compute_xg_team_ratings([_row(1, 1, 2, "2025-08-10", 1.0, 1.0, 1.0, 1.0)], 0) == {}
