"""TODO 11.32: rivalita/styl/únava/motivace z webového textu jen z ověřených claimů s ověřeným týmem (běh M979)."""
import sqlite3

import pytest

from app.database.research_repository import ResearchRepository
from app.database.schema import initialize_database
from app.statistics.research_context import ResearchContextMapper

CUTOFF = "2026-11-02T21:09:21+00:00"


def _claim(value, confidence=0.6, predicate="x", subject="s"):
    return {"subject": subject, "predicate": predicate, "normalized_value": value, "object": value,
            "confidence": confidence, "status": "VALID", "source_date": "2026-11-01T10:00:00+00:00", "evidence_list": []}


@pytest.fixture
def db(tmp_path):
    path = str(tmp_path / "ctx.db")
    initialize_database(path)
    with sqlite3.connect(path) as conn:
        conn.execute("INSERT INTO teams(id, name, normalized_name) VALUES (1,'SK Artis Brno','artis brno'),(2,'Bohemians 1905','bohemians 1905')")
        conn.execute("INSERT INTO matches(id, competition, home_team_id, away_team_id, scheduled_at) VALUES (1,'Chance Liga',1,2,'2026-11-04T17:00:00+00:00')")
        conn.execute("INSERT INTO runs(id, run_id, status, started_at) VALUES (1,'R1','RUNNING','2026-11-02T20:00:00')")
    return path


def _ctx(db):
    return ResearchContextMapper.from_db(db, 1, 1, CUTOFF)


def _match(db, domain, *claims):
    ResearchRepository(db).save_match_context(1, "R1", CUTOFF, list(claims), domain=domain)


def test_derby_text_about_other_clubs_gives_no_rivalry(db):
    _match(db, "RIVALRY", _claim("The Vršovice Derby is the second most prestigious derby in Prague (after Slavia-Sparta)."))
    assert "rivalry" not in _ctx(db)["match_context"]


def test_rivalry_needs_both_teams_and_confidence(db):
    _match(db, "RIVALRY", _claim("Artis Brno vs Bohemians 1905 is a fierce rivalry.", confidence=0.39))
    assert "rivalry" not in _ctx(db)["match_context"]
    _match(db, "RIVALRY", _claim("Artis Brno vs Bohemians 1905 is a fierce rivalry.", confidence=0.6))
    assert _ctx(db)["match_context"]["rivalry"] == 0.5


def test_style_needs_clear_vote_margin(db):
    _match(db, "STYLE_MATCHUP", _claim("Artis Brno rely on counter-attack and transition play."))
    assert "style_goal_factor" not in _ctx(db)["match_context"]  # 1 hlas nestačí
    _match(db, "STYLE_MATCHUP", _claim("Bohemians 1905 press high press and win the ball in transition."))
    assert _ctx(db)["match_context"]["style_goal_factor"] == 1.05


def test_high_defensive_line_is_not_a_defensive_vote():
    text = "Bohemians use a high defensive line."
    assert ResearchContextMapper._DEFENSIVE_STYLE_RE.search(text) is None


def test_team_fatigue_only_from_claims_mentioning_that_team(db):
    repo = ResearchRepository(db)
    repo.save_team_profile(1, CUTOFF, "R1", [_claim("Sparta Praha face fixture congestion and travel.")])
    assert "fatigue" not in _ctx(db)["home_context"]
    repo.save_team_profile(1, CUTOFF, "R1", [_claim("SK Artis Brno face fixture congestion this month.")])
    assert _ctx(db)["home_context"]["fatigue"] == 0.35


def test_low_confidence_team_claim_is_ignored(db):
    ResearchRepository(db).save_team_profile(2, CUTOFF, "R1", [_claim("Bohemians 1905 have short rest.", confidence=0.39)])
    assert "fatigue" not in _ctx(db)["away_context"]


def test_keywords_are_whole_words_without_diacritics():
    assert ResearchContextMapper._team_context(["Artis má únavu z cestování"]).get("fatigue") == 0.35
    assert "fatigue" not in ResearchContextMapper._team_context(["They unravel the plot"])
