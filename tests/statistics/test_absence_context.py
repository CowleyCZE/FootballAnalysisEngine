"""TODO 2.3 – absence/sestavy: jen ověřené claims (>= 2 nezávislí vydavatelé, datum <= cutoff), omezený multiplikátor."""
import json
import sqlite3

import pytest

from app.database.schema import initialize_database
from app.statistics.research_context import ResearchContextMapper
from app.statistics.score_predictor import ExactScorePredictor

CUTOFF = "2026-10-15T12:00:00+00:00"


def _fact(name, status, urls, source_date="2026-10-14T10:00:00+00:00", published="2026-10-14T10:00:00+00:00"):
    return {
        "subject": name, "predicate": "availability_status", "value": f"{name}:{status}",
        "confidence": 0.9, "source_date": source_date,
        "evidence": [{"source_url": u, "text_fragment": "x", "published_at": published} for u in urls],
    }


TWO = ["https://www.idnes.cz/a", "https://sport.cz/b"]


@pytest.fixture
def db(tmp_path):
    path = str(tmp_path / "absence.db")
    initialize_database(path)
    with sqlite3.connect(path) as conn:
        conn.execute("INSERT INTO teams(id, name, normalized_name) VALUES (1,'A','a'),(2,'B','b')")
        conn.execute("INSERT INTO matches(id, competition, home_team_id, away_team_id, scheduled_at) VALUES (1,'Liga',1,2,'2026-10-16T18:00:00+00:00')")
        conn.execute("INSERT INTO runs(id, run_id, status, started_at) VALUES (1,'R1','RUNNING','2026-10-15T10:00:00')")
    return path


def _store(db, team_id, facts):
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO team_profile_snapshots(team_id, data_cutoff_at, source_run_id, profile_json) VALUES (?,?,?,?)",
            (team_id, CUTOFF, "R1", json.dumps({"schema_version": 1, "facts": facts})),
        )


def _home(db):
    return ResearchContextMapper.from_db(db, 1, 1, CUTOFF)["home_context"]


def test_verified_absences_give_bounded_multipliers(db):
    _store(db, 1, [_fact("Jan Novak", "UNAVAILABLE", TWO), _fact("Petr Svoboda", "SUSPENDED", TWO),
                   _fact("Karel Dvorak", "DOUBTFUL", TWO)])
    ctx = _home(db)
    assert ctx["attack_multiplier"] == pytest.approx(0.95)   # 1 - 0.02 * 2.5
    assert ctx["defence_multiplier"] == pytest.approx(1.025)
    assert ctx["absences_counted"] == 3


def test_single_publisher_or_post_cutoff_or_undated_claims_are_ignored(db):
    _store(db, 1, [
        _fact("Jen Jeden", "UNAVAILABLE", ["https://idnes.cz/a", "https://www.idnes.cz/b"]),       # 1 vydavatel
        _fact("Pozdni Zdroj", "UNAVAILABLE", TWO, source_date="2026-10-16T10:00:00+00:00"),        # po cutoffu
        _fact("Pozdni Evidence", "UNAVAILABLE", TWO, published="2026-10-15T13:00:00+00:00"),       # evidence po cutoffu
        _fact("Bez Data", "UNAVAILABLE", TWO, source_date=None),                                   # datum se neodvozuje
    ])
    ctx = _home(db)
    assert "attack_multiplier" not in ctx and "defence_multiplier" not in ctx


def test_multiplier_is_capped(db):
    _store(db, 1, [_fact(f"Hrac Cislo{i}", "UNAVAILABLE", TWO) for i in range(12)])
    ctx = _home(db)
    assert ctx["attack_multiplier"] == pytest.approx(0.92)
    assert ctx["defence_multiplier"] == pytest.approx(1.05)


def test_without_claims_context_is_unchanged(db):
    assert _home(db) == {}
    _store(db, 1, [{"subject": "A", "predicate": "absence_report", "value": "A:absences:nic", "source_date": "2026-10-14T10:00:00+00:00", "evidence": []}])
    assert "attack_multiplier" not in _home(db)


def test_predictor_applies_and_reports_multipliers():
    base = ExactScorePredictor.predict([], 1, 2)
    adj = ExactScorePredictor.predict([], 1, 2, home_context={"attack_multiplier": 0.95, "defence_multiplier": 1.025, "absences_counted": 3})
    assert adj["expected_home_goals"] < base["expected_home_goals"]
    assert adj["expected_away_goals"] > base["expected_away_goals"]
    mult = adj["factors"]["context_multipliers"]
    assert mult["home_attack"] == 0.95 and mult["home_absences"] == 3
    assert "context_multipliers" not in base["factors"]
