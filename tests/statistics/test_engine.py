import sqlite3
import pytest
from app.statistics.engine import StatisticalEngine
from app.statistics.repository import StatisticsRepository
from app.statistics.models import MatchStatistics

@pytest.fixture
def setup_test_db(tmp_path):
    db_file = tmp_path / "test_football.db"
    conn = sqlite3.connect(db_file)
    cursor = conn.cursor()
    
    # Získání schématu
    with open("database/schema.sql", "r") as f:
        cursor.executescript(f.read())
        
    # Vložení testovacích dat
    cursor.execute("INSERT INTO teams (id, name, normalized_name) VALUES (10, 'Team A', 'team_a'), (20, 'Team B', 'team_b')")
    cursor.execute("INSERT INTO runs (id, run_id, status, started_at) VALUES (100, 'run_100', 'RUNNING', '2026-10-02T20:00:00')")
    
    # 2 starší zápasy
    cursor.execute("INSERT INTO matches (id, home_team_id, away_team_id, scheduled_at, competition) VALUES (1, 10, 20, '2026-09-01T15:00:00', 'Test League')")
    cursor.execute("INSERT INTO matches (id, home_team_id, away_team_id, scheduled_at, competition) VALUES (2, 20, 10, '2026-09-10T15:00:00', 'Test League')")
    
    # 1 budoucí zápas (pro test Data Leakage)
    cursor.execute("INSERT INTO matches (id, home_team_id, away_team_id, scheduled_at, competition) VALUES (3, 10, 20, '2026-10-05T15:00:00', 'Test League')")
    
    conn.commit()
    conn.close()
    
    # Vložení statistik k zápasům
    repo = StatisticsRepository(str(db_file))
    repo.save_match_statistics(MatchStatistics(match_id=1, home_goals=2, away_goals=0, home_shots=10, home_shots_on_target=4, home_xg=1.8, away_xg=0.4))
    repo.save_match_statistics(MatchStatistics(match_id=2, home_goals=1, away_goals=1, home_shots=8, home_shots_on_target=3, home_xg=1.0, away_xg=1.1))
    repo.save_match_statistics(MatchStatistics(match_id=3, home_goals=5, away_goals=5, home_shots=20, home_shots_on_target=10))

    return str(db_file)

def test_statistical_engine_execution_and_leakage_prevention(setup_test_db):
    engine = StatisticalEngine(db_path=setup_test_db)
    
    # Cutoff nastaven k 2. říjnu 2026 (zápas id=3 z 5. října NESMÍ vstoupit do výpočtu)
    cutoff = "2026-10-02T23:59:59"
    
    report = engine.run_match_statistics(
        match_id=1,
        run_id=100,
        home_team_id=10,
        away_team_id=20,
        cutoff_datetime=cutoff
    )
    
    assert report["status"] == "COMPLETED"
    assert report["home_team"]["form"]["sample_size"] == 2  # Pouze zápasy 1 a 2! Zápas 3 byl odfiltrován
    assert report["home_team"]["form"]["points"] == 4  # 1x výhra (3b), 1x remíza (1b)
    
    # Kontrola uložení snapshotu v DB
    conn = sqlite3.connect(setup_test_db)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM statistical_snapshots WHERE run_id = 100").fetchone()
    conn.close()
    
    assert row is not None
    assert row["metric"] == "form_points"
    assert row["value"] == 4.0
    assert row["data_cutoff_at"] == cutoff