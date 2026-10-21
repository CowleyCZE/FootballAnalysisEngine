"""TODO 2.2 – síla soupeřů (model v5): góly se vážou na kvalitu soupeřů, shrinkage k 1,0."""
import sqlite3

import pytest

from app.database.schema import initialize_database
from app.statistics.engine import StatisticalEngine
from app.statistics.repository import StatisticsRepository
from app.statistics.score_predictor import ExactScorePredictor

LEAGUE_MEAN = 1.3


def _row(match_id, home, away, hg, ag, day):
    return {"match_id": match_id, "home_team_id": home, "away_team_id": away,
            "home_goals": hg, "away_goals": ag, "scheduled_at": f"2026-09-{day:02d}T15:00:00+00:00"}


def _league_rows():
    # Tým 10 má silnou obranu (nic nedostal), tým 11 slabou (dostal 4 góly v každém zápase).
    rows = [_row(i, 20 + i, 10, 0, 1, i) for i in range(1, 4)]
    rows += [_row(10 + i, 30 + i, 11, 4, 1, i) for i in range(1, 4)]
    return rows


def test_model_version_is_v5():
    assert ExactScorePredictor.MODEL_VERSION == "poisson-dc-context-v5"


def test_opponent_ratings_direction_and_bounds():
    ratings = ExactScorePredictor.opponent_ratings(_league_rows(), LEAGUE_MEAN)
    lo, hi = ExactScorePredictor.RATING_BOUNDS
    assert ratings[10][1] < 1.0 < ratings[11][1]  # obrana: silná < 1 < slabá
    assert all(lo <= v <= hi for pair in ratings.values() for v in pair)
    assert ExactScorePredictor.opponent_ratings([], LEAGUE_MEAN) == {}


def test_opponent_ratings_shrink_toward_one_with_few_games():
    one = ExactScorePredictor.opponent_ratings([_row(1, 1, 2, 5, 0, 1)], LEAGUE_MEAN)
    many = ExactScorePredictor.opponent_ratings([_row(i, 1, 2, 5, 0, i) for i in range(1, 21)], LEAGUE_MEAN)
    assert 1.0 < one[1][0] < many[1][0] <= ExactScorePredictor.RATING_BOUNDS[1]


def _predict(opponent_id, league_rows):
    history = [_row(100 + i, 1, opponent_id, 2, 1, 10 + i) for i in range(4)]
    return ExactScorePredictor.predict(
        history, 1, 2, league_stats={"matches": 30, "mean": LEAGUE_MEAN}, league_rows=league_rows
    )


def test_goals_against_strong_defence_are_worth_more():
    vs_strong = _predict(10, _league_rows())
    vs_weak = _predict(11, _league_rows())
    assert vs_strong["factors"]["opponent_adjusted"] is True
    assert vs_strong["expected_home_goals"] > vs_weak["expected_home_goals"]


def test_without_league_rows_no_adjustment():
    pred = _predict(10, None)
    assert pred["factors"]["opponent_adjusted"] is False
    assert pred["expected_home_goals"] == _predict(11, None)["expected_home_goals"]
    # méně než MIN_LEAGUE_MATCHES zápasů → bez úpravy
    few = _predict(10, _league_rows()[:2])
    assert few["factors"]["opponent_adjusted"] is False


def test_repository_league_matches_before_kickoff_only(tmp_path):
    db_file = str(tmp_path / "ratings.db")
    initialize_database(db_file)
    with sqlite3.connect(db_file) as conn:
        conn.execute("INSERT INTO teams(id, name, normalized_name) VALUES (1,'A','a'),(2,'B','b')")
        conn.execute("INSERT INTO competitions(id, name, country) VALUES (1,'Liga','CZ'),(2,'Jina','CZ')")
        rows = [
            (1, 1, 1, 2, "2026-09-01T15:00:00+00:00", (1, 0)),
            (2, 1, 2, 1, "2026-09-08T15:00:00+00:00", (2, 2)),
            (3, 1, 1, 2, "2026-10-15T20:00:00+00:00", (9, 9)),  # po výkopu
            (4, 2, 1, 2, "2026-09-02T15:00:00+00:00", (7, 7)),  # jiná soutěž
        ]
        for mid, comp, h, a, when, goals in rows:
            conn.execute(
                "INSERT INTO matches(id, competition, competition_id, home_team_id, away_team_id, scheduled_at) "
                "VALUES (?, 'Liga', ?, ?, ?, ?)", (mid, comp, h, a, when))
            conn.execute("INSERT INTO match_statistics(match_id, home_goals, away_goals) VALUES (?, ?, ?)",
                         (mid, goals[0], goals[1]))
        conn.execute(
            "INSERT INTO matches(id, competition, competition_id, home_team_id, away_team_id, scheduled_at) "
            "VALUES (100, 'Liga', 1, 1, 2, '2026-10-15T18:00:00+00:00')")
    got = StatisticsRepository(db_file).get_league_matches(100, "2026-10-16T12:00:00+00:00")
    assert sorted(r["match_id"] for r in got) == [1, 2]


def test_engine_reports_opponent_adjustment(tmp_path, monkeypatch):
    monkeypatch.setenv("FAE_AUTO_HISTORY", "0")
    db_file = str(tmp_path / "engine_ratings.db")
    initialize_database(db_file)
    with sqlite3.connect(db_file) as conn:
        conn.execute("INSERT INTO teams(id, name, normalized_name) VALUES (1,'A','a'),(2,'B','b'),(3,'C','c')")
        conn.execute("INSERT INTO competitions(id, name, country) VALUES (1,'Liga','CZ')")
        conn.execute("INSERT INTO runs(id, run_id, status, started_at) VALUES (1,'R1','RUNNING','2026-10-15T10:00:00')")
        pairs = [(1, 2), (2, 3), (3, 1), (2, 1), (3, 2), (1, 3)]
        for i, (h, a) in enumerate(pairs, start=1):
            conn.execute(
                "INSERT INTO matches(id, competition, competition_id, home_team_id, away_team_id, scheduled_at) "
                "VALUES (?, 'Liga', 1, ?, ?, ?)", (i, h, a, f"2026-09-{i:02d}T15:00:00+00:00"))
            conn.execute("INSERT INTO match_statistics(match_id, home_goals, away_goals) VALUES (?, 2, 1)", (i,))
        conn.execute(
            "INSERT INTO matches(id, competition, competition_id, home_team_id, away_team_id, scheduled_at) "
            "VALUES (100, 'Liga', 1, 1, 2, '2026-10-15T18:00:00+00:00')")
    report = StatisticalEngine(db_path=db_file).run_match_statistics(100, 1, 1, 2, "2026-10-16T12:00:00+00:00")
    assert report["prediction"]["model_version"] == "poisson-dc-context-v5"
    assert report["prediction"]["factors"]["opponent_adjusted"] is True
