"""TODO 2.1 (ligový průměr gólů ze celé ligy) a 2.4 (únik dat – zápasy po výkopu cílového zápasu)."""
import json
import sqlite3

import pytest

from app.database.schema import initialize_database
from app.statistics.engine import StatisticalEngine
from app.statistics.repository import StatisticsRepository
from app.statistics.score_predictor import ExactScorePredictor

CUTOFF = "2026-10-16T12:00:00+00:00"
KICKOFF = "2026-10-15T18:00:00+00:00"


def _add_match(conn, match_id, home, away, when, goals=None, competition_id=1):
    conn.execute(
        "INSERT INTO matches(id, competition, competition_id, home_team_id, away_team_id, scheduled_at) "
        "VALUES (?, 'Liga', ?, ?, ?, ?)",
        (match_id, competition_id, home, away, when),
    )
    if goals is not None:
        conn.execute(
            "INSERT INTO match_statistics(match_id, home_goals, away_goals) VALUES (?, ?, ?)",
            (match_id, goals[0], goals[1]),
        )


@pytest.fixture
def league_db(tmp_path, monkeypatch):
    monkeypatch.setenv("FAE_AUTO_HISTORY", "0")
    db_file = str(tmp_path / "league.db")
    initialize_database(db_file)
    with sqlite3.connect(db_file) as conn:
        conn.execute(
            "INSERT INTO teams(id, name, normalized_name) VALUES (1,'A','a'),(2,'B','b'),(3,'C','c'),(4,'D','d')"
        )
        conn.execute("INSERT INTO competitions(id, name, country) VALUES (1,'Liga','CZ'),(2,'Jina liga','CZ')")
        conn.execute("INSERT INTO runs(id, run_id, status, started_at) VALUES (1,'R1','RUNNING','2026-10-15T10:00:00')")
        # Šest odehraných zápasů mezi třemi týmy, vždy 2:1 → 1,5 gólu na tým a zápas.
        pairs = [(1, 2), (2, 3), (3, 1), (2, 1), (3, 2), (1, 3)]
        for i, (h, a) in enumerate(pairs, start=1):
            _add_match(conn, i, h, a, f"2026-09-{i:02d}T15:00:00+00:00", goals=(2, 1))
        # Cílový zápas (bez výsledku).
        _add_match(conn, 100, 1, 2, KICKOFF)
        # Zápas ve stejné lize po výkopu cílového zápasu, ale před cutoffem – nesmí se použít.
        _add_match(conn, 101, 1, 2, "2026-10-15T20:00:00+00:00", goals=(9, 9))
        # Zápas jiné soutěže – nesmí ovlivnit průměr.
        _add_match(conn, 102, 3, 4, "2026-09-20T15:00:00+00:00", goals=(8, 8), competition_id=2)
    return db_file


def test_league_goal_stats_uses_whole_competition_before_kickoff(league_db):
    stats = StatisticsRepository(league_db).get_league_goal_stats(100, CUTOFF)
    assert stats["matches"] == 6  # bez cílového zápasu, bez zápasu po výkopu, bez jiné soutěže
    assert stats["mean"] == pytest.approx(1.5)


def test_league_goal_stats_empty_without_history(league_db):
    with sqlite3.connect(league_db) as conn:
        _add_match(conn, 200, 3, 4, "2026-10-20T18:00:00+00:00", competition_id=2)
        conn.execute("DELETE FROM match_statistics WHERE match_id = 102")
    stats = StatisticsRepository(league_db).get_league_goal_stats(200, CUTOFF)
    assert stats == {"matches": 0, "mean": None}


def test_predictor_prefers_league_mean_and_falls_back_when_league_small():
    with_league = ExactScorePredictor.predict([], 1, 2, league_stats={"matches": 30, "mean": 1.6})
    assert with_league["factors"]["league_mean_source"] == "league"
    assert with_league["factors"]["league_mean_goals"] == pytest.approx(1.6)
    assert with_league["factors"]["league_matches"] == 30

    too_small = ExactScorePredictor.predict([], 1, 2, league_stats={"matches": 2, "mean": 3.0})
    assert too_small["factors"]["league_mean_source"] == "default"
    assert too_small["factors"]["league_mean_goals"] == pytest.approx(ExactScorePredictor.DEFAULT_LEAGUE_MEAN)


def test_engine_uses_league_mean_and_excludes_matches_after_kickoff(league_db):
    report = StatisticalEngine(db_path=league_db).run_match_statistics(100, 1, 1, 2, CUTOFF)

    factors = report["prediction"]["factors"]
    assert factors["league_mean_source"] == "league"
    assert factors["league_matches"] == 6
    assert factors["league_mean_goals"] == pytest.approx(1.5)

    # Tým 1 i 2 odehrály 4 ligové zápasy před výkopem; zápas 101 (po výkopu) není ve vzorku.
    assert factors["home_history_matches"] == 4
    assert factors["away_history_matches"] == 4
    assert report["sample_size"] == 8

    with sqlite3.connect(league_db) as conn:
        raw = conn.execute("SELECT factors_json FROM match_predictions WHERE run_id='R1'").fetchone()[0]
    assert json.loads(raw)["league_mean_source"] == "league"
