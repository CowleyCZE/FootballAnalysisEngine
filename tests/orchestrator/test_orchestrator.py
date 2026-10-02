import sqlite3
import pytest
from datetime import datetime
from app.orchestrator.models import AnalysisRequest
from app.orchestrator.orchestrator import MatchOrchestrator
from app.orchestrator.match_resolver import MatchNotFoundException, AmbiguousMatchException

@pytest.fixture
def test_db(tmp_path):
    db_file = tmp_path / "test_football.db"
    conn = sqlite3.connect(db_file)
    cursor = conn.cursor()
    
    # Příprava testovacích tabulek
    cursor.execute("CREATE TABLE teams (id INTEGER PRIMARY KEY, name TEXT);")
    cursor.execute("CREATE TABLE competitions (id INTEGER PRIMARY KEY, name TEXT);")
    cursor.execute("""
        CREATE TABLE matches (
            id INTEGER PRIMARY KEY,
            home_team_id INTEGER,
            away_team_id INTEGER,
            competition_id INTEGER,
            scheduled_at TEXT
        );
    """)
    
    # Vložení testovacích dat
    cursor.execute("INSERT INTO teams VALUES (1, 'Sparta Praha'), (2, 'Slavia Praha');")
    cursor.execute("INSERT INTO competitions VALUES (1, '1. Liga');")
    cursor.execute("INSERT INTO matches VALUES (100, 1, 2, 1, '2026-10-10 18:00:00');")
    
    conn.commit()
    conn.close()
    return str(db_file)

def test_start_analysis_run_success(test_db):
    orchestrator = MatchOrchestrator(db_path=test_db)
    
    req = AnalysisRequest(
        home_team="Sparta",
        away_team="Slavia",
        competition="1. Liga",
        scheduled_at=datetime(2026, 10, 10, 18, 0)
    )
    
    result = orchestrator.start_analysis_run(req)
    
    assert result["run_id"] is not None
    assert result["status"] == "RESEARCHING"
    assert result["tasks_count"] > 0

def test_match_not_found(test_db):
    orchestrator = MatchOrchestrator(db_path=test_db)
    
    req = AnalysisRequest(
        home_team="NeexistujiciTymA",
        away_team="NeexistujiciTymB",
        competition="1. Liga",
        scheduled_at=datetime(2026, 10, 10, 18, 0)
    )
    
    with pytest.raises(MatchNotFoundException):
        orchestrator.start_analysis_run(req)