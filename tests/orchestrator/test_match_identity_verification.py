import sqlite3
import pytest
from datetime import datetime, timezone
from app.orchestrator.models import AnalysisRequest
from app.orchestrator.match_resolver import (
    MatchResolver,
    MatchNotFoundException,
    AmbiguousMatchException,
    UnverifiedMatchException,
)
from app.orchestrator.orchestrator import MasterOrchestrator, MatchOrchestrator
from app.search.relevance import calculate_identity_confidence
from app.search.models import SearchResult
from app.database.schema import initialize_database


@pytest.fixture
def test_db(tmp_path):
    db_file = str(tmp_path / "test_football.db")
    initialize_database(db_file)
    with sqlite3.connect(db_file) as conn:
        conn.execute("INSERT INTO competitions (id, name, country) VALUES (1, 'Chance Liga', 'Czech Republic')")
        conn.execute("INSERT INTO competitions (id, name, country) VALUES (2, 'Premier League', 'England')")
        conn.execute("INSERT INTO teams (id, name, normalized_name) VALUES (10, 'AC Sparta Praha', 'ac sparta praha')")
        conn.execute("INSERT INTO teams (id, name, normalized_name) VALUES (20, 'SK Slavia Praha', 'sk slavia praha')")
        conn.execute("INSERT INTO teams (id, name, normalized_name) VALUES (30, 'FC Viktoria Plzen', 'fc viktoria plzen')")
        conn.commit()
    return db_file


def test_scenario_1_teams_comp_exist_but_match_not_in_schedule(test_db):
    """
    1. V databázi existují oba týmy a soutěž, ale konkrétní zápas není v rozpisu.
    Výsledek musí být odmítnut jako neověřený nebo nenalezený.
    """
    resolver = MatchResolver(db_path=test_db)
    req = AnalysisRequest(
        home_team="AC Sparta Praha",
        away_team="SK Slavia Praha",
        competition="Chance Liga",
        scheduled_at=datetime(2025, 5, 10, 18, 0, tzinfo=timezone.utc),
    )
    with pytest.raises(UnverifiedMatchException) as exc_info:
        resolver.resolve_or_create(req)
    assert "neexistuje v autoritativním rozpisu" in str(exc_info.value)

    # Verify match created in DB is UNVERIFIED
    with sqlite3.connect(test_db) as conn:
        row = conn.execute("SELECT status FROM matches WHERE home_team_id=10 AND away_team_id=20").fetchone()
        assert row is not None
        assert row[0] == "UNVERIFIED"


def test_scenario_2_same_teams_play_on_different_date(test_db):
    """
    2. Stejné týmy hrají v jiném datu. Požadovaný zápas se nesmí přijmout.
    """
    with sqlite3.connect(test_db) as conn:
        conn.execute(
            "INSERT INTO matches (id, home_team_id, away_team_id, competition_id, competition, scheduled_at, status) "
            "VALUES (100, 10, 20, 1, 'Chance Liga', '2025-05-10T18:00:00+00:00', 'RESOLVED')"
        )
        conn.commit()

    resolver = MatchResolver(db_path=test_db)
    req_different_date = AnalysisRequest(
        home_team="AC Sparta Praha",
        away_team="SK Slavia Praha",
        competition="Chance Liga",
        scheduled_at=datetime(2025, 5, 11, 18, 0, tzinfo=timezone.utc),
    )
    with pytest.raises((MatchNotFoundException, UnverifiedMatchException)):
        resolver.resolve(req_different_date)


def test_scenario_3_home_and_away_teams_swapped(test_db):
    """
    3. Domácí a hostující týmy jsou prohozené. Výsledek se nesmí přijmout jako přesná shoda.
    """
    with sqlite3.connect(test_db) as conn:
        conn.execute(
            "INSERT INTO matches (id, home_team_id, away_team_id, competition_id, competition, scheduled_at, status) "
            "VALUES (101, 10, 20, 1, 'Chance Liga', '2025-05-10T18:00:00+00:00', 'RESOLVED')"
        )
        conn.commit()

    resolver = MatchResolver(db_path=test_db)
    req_swapped = AnalysisRequest(
        home_team="SK Slavia Praha",
        away_team="AC Sparta Praha",
        competition="Chance Liga",
        scheduled_at=datetime(2025, 5, 10, 18, 0, tzinfo=timezone.utc),
    )
    with pytest.raises((MatchNotFoundException, UnverifiedMatchException)):
        resolver.resolve(req_swapped)


def test_scenario_4_teams_match_but_competition_differs(test_db):
    """
    4. Týmy odpovídají, ale soutěž je jiná. Výsledek se nesmí přijmout.
    """
    with sqlite3.connect(test_db) as conn:
        conn.execute(
            "INSERT INTO matches (id, home_team_id, away_team_id, competition_id, competition, scheduled_at, status) "
            "VALUES (102, 10, 20, 1, 'Chance Liga', '2025-05-10T18:00:00+00:00', 'RESOLVED')"
        )
        conn.commit()

    resolver = MatchResolver(db_path=test_db)
    req_different_comp = AnalysisRequest(
        home_team="AC Sparta Praha",
        away_team="SK Slavia Praha",
        competition="Premier League",
        scheduled_at=datetime(2025, 5, 10, 18, 0, tzinfo=timezone.utc),
    )
    with pytest.raises((MatchNotFoundException, UnverifiedMatchException)):
        resolver.resolve(req_different_comp)


def test_scenario_5_article_about_one_team_does_not_confirm_match():
    """
    5. Vyhledávání vrátí článek o jednom z týmů, ale článek nepotvrzuje konkrétní utkání. Nesmí dojít k potvrzení identity zápasu.
    """
    article = SearchResult(
        title="Sparta Praha signs a new striker",
        url="https://example.com/sparta-transfer",
        content="Sparta Praha announced today the signing of a new forward from the Dutch league.",
    )
    conf = calculate_identity_confidence(
        article,
        home_team="Sparta Praha",
        away_team="Slavia Praha",
        competition="Chance Liga",
        scheduled_at=datetime(2025, 5, 10, 18, 0),
    )
    assert conf < 0.6  # Rejected, since away team Slavia Praha is completely missing


def test_scenario_6_correct_match_confirmed_by_authoritative_schedule(test_db):
    """
    6. Existuje jeden správný zápas potvrzený důvěryhodným zdrojem. Zápas lze bezpečně identifikovat.
    """
    with sqlite3.connect(test_db) as conn:
        conn.execute(
            "INSERT INTO matches (id, home_team_id, away_team_id, competition_id, competition, scheduled_at, status) "
            "VALUES (103, 10, 20, 1, 'Chance Liga', '2025-05-10T18:00:00+00:00', 'RESOLVED')"
        )
        conn.commit()

    resolver = MatchResolver(db_path=test_db)
    req = AnalysisRequest(
        home_team="AC Sparta Praha",
        away_team="SK Slavia Praha",
        competition="Chance Liga",
        scheduled_at=datetime(2025, 5, 10, 18, 0, tzinfo=timezone.utc),
    )
    identity = resolver.resolve(req)
    assert identity.match_id == 103
    assert identity.status == "RESOLVED"


def test_scenario_7_multiple_matching_records_are_ambiguous(test_db):
    """
    7. Existuje více odpovídajících záznamů. Systém je musí označit jako nejednoznačné a nesmí náhodně vybrat jeden.
    """
    with sqlite3.connect(test_db) as conn:
        conn.execute(
            "INSERT INTO matches (id, home_team_id, away_team_id, competition_id, competition, scheduled_at, status) "
            "VALUES (104, 10, 20, 1, 'Chance Liga', '2025-05-10T18:00:00+00:00', 'RESOLVED')"
        )
        conn.execute(
            "INSERT INTO matches (id, home_team_id, away_team_id, competition_id, competition, scheduled_at, status) "
            "VALUES (105, 10, 20, 1, 'Chance Liga', '2025-05-10T18:00:00+00:00', 'RESOLVED')"
        )
        conn.commit()

    resolver = MatchResolver(db_path=test_db)
    req = AnalysisRequest(
        home_team="AC Sparta Praha",
        away_team="SK Slavia Praha",
        competition="Chance Liga",
        scheduled_at=datetime(2025, 5, 10, 18, 0, tzinfo=timezone.utc),
    )
    with pytest.raises(AmbiguousMatchException):
        resolver.resolve(req)


def test_scenario_8_unverified_request_cannot_start_pipeline(test_db):
    """
    8. Neověřený požadavek nesmí vytvořit ani spustit analytický běh.
    """
    master = MasterOrchestrator(db_path=test_db)
    orc = MatchOrchestrator(db_path=test_db)

    req = AnalysisRequest(
        home_team="AC Sparta Praha",
        away_team="SK Slavia Praha",
        competition="Chance Liga",
        scheduled_at=datetime(2025, 5, 10, 18, 0, tzinfo=timezone.utc),
    )

    with pytest.raises((MatchNotFoundException, UnverifiedMatchException)):
        orc.start_analysis_run(req)

    # Check unverified match ID in DB directly
    with sqlite3.connect(test_db) as conn:
        unverified_id = conn.execute("SELECT id FROM matches WHERE status='UNVERIFIED'").fetchone()[0]

    with pytest.raises(ValueError) as exc_info:
        master.start_pipeline(unverified_id)
    assert "UNVERIFIED" in str(exc_info.value)


def test_scenario_9_verification_error_is_not_treated_as_success(test_db):
    """
    9. Žádná chyba při ověřování nesmí být omylem interpretována jako úspěch.
    """
    resolver = MatchResolver(db_path=test_db)
    req = AnalysisRequest(
        home_team="NonExistent Home Team",
        away_team="NonExistent Away Team",
        competition="Unknown League",
        scheduled_at=datetime(2025, 5, 10, 18, 0, tzinfo=timezone.utc),
    )
    with pytest.raises(MatchNotFoundException):
        resolver.resolve_or_create(req)


def test_scenario_10_existing_tests_and_valid_verified_matches_pass(test_db):
    """
    10. Dosavadní testy úspěšného průchodu pipeline zůstávají funkční pro správně ověřený zápas.
    """
    with sqlite3.connect(test_db) as conn:
        conn.execute(
            "INSERT INTO matches (id, home_team_id, away_team_id, competition_id, competition, scheduled_at, status) "
            "VALUES (200, 10, 20, 1, 'Chance Liga', '2025-05-10T18:00:00+00:00', 'RESOLVED')"
        )
        conn.commit()

    master = MasterOrchestrator(db_path=test_db)
    run_id = master.start_pipeline(200)
    assert run_id is not None
    assert "M200_" in run_id
