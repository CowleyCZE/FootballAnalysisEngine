"""TODO 2.5 – scripts/backtest.py: metriky bez úniku dat, DB jen pro čtení."""
import hashlib
import math
import sqlite3
from datetime import date, timedelta

import pytest

from app.database.schema import initialize_database
from scripts import backtest


@pytest.fixture
def played_db(tmp_path):
    path = str(tmp_path / "backtest.db")
    initialize_database(path)
    pairs = [(1, 2), (2, 3), (3, 1)] * 4
    goals = [(2, 1), (1, 1), (0, 2), (3, 0), (1, 0), (2, 2), (1, 2), (2, 0), (0, 0), (2, 1), (1, 3), (1, 1)]
    with sqlite3.connect(path) as conn:
        conn.execute("INSERT INTO teams(id, name, normalized_name) VALUES (1,'A','a'),(2,'B','b'),(3,'C','c')")
        conn.execute("INSERT INTO competitions(id, name, country) VALUES (1,'Liga','CZ')")
        for i, ((h, a), (hg, ag)) in enumerate(zip(pairs, goals), start=1):
            when = (date(2026, 8, 1) + timedelta(days=7 * i)).isoformat() + "T15:00:00+00:00"
            conn.execute(
                "INSERT INTO matches(id, competition, competition_id, home_team_id, away_team_id, scheduled_at) "
                "VALUES (?, 'Liga', 1, ?, ?, ?)", (i, h, a, when))
            conn.execute("INSERT INTO match_statistics(match_id, home_goals, away_goals) VALUES (?, ?, ?)", (i, hg, ag))
    return path


def _digest(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def test_backtest_metrics_and_skipping(played_db):
    before = _digest(played_db)
    r = backtest.run_backtest(played_db, min_history=3)
    assert r["matches_total"] == 12
    assert r["evaluated"] > 0
    assert r["skipped_insufficient_history"] > 0  # první zápasy nemají historii
    assert r["evaluated"] + r["skipped_insufficient_history"] == 12
    assert 0.0 <= r["exact_score_accuracy"] <= 1.0
    assert 0.0 <= r["outcome_1x2_accuracy"] <= 1.0
    assert 0.0 < r["log_loss_1x2"] < 3.0
    assert r["baseline_uniform_log_loss"] == round(math.log(3), 4)
    assert _digest(played_db) == before  # jen čtení


def test_backtest_does_not_use_the_target_match(played_db):
    # Poslední zápas změníme na extrémní výsledek: predikce k jeho výkopu na něm nesmí záviset.
    r1 = backtest.run_backtest(played_db, min_history=3, limit=1)
    with sqlite3.connect(played_db) as conn:
        conn.execute("UPDATE match_statistics SET home_goals = 9, away_goals = 9 WHERE match_id = 12")
    r2 = backtest.run_backtest(played_db, min_history=3, limit=1)
    assert r1["evaluated"] == r2["evaluated"] == 1
    # skutečný výsledek se změnil (jiná chyba), ale model viděl stejná data → chyba gólů musí vzrůst
    assert r2["mean_abs_goal_error"] > r1["mean_abs_goal_error"]


def test_backtest_main_output_and_missing_db(played_db, tmp_path, capsys):
    assert backtest.main(["--db", played_db, "--min-history", "3"]) == 0
    out = capsys.readouterr().out
    assert "Přesné skóre" in out and "Log-loss" in out
    assert backtest.main(["--db", str(tmp_path / "neni.db")]) == 2
