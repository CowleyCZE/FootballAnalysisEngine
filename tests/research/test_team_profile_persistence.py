import sqlite3

from app.database.research_repository import ResearchRepository
from app.database.schema import initialize_database


def test_claims_for_standalone_team_research_allow_null_match(tmp_path):
    db_path = str(tmp_path / "team-profile.db")
    initialize_database(db_path)
    repo = ResearchRepository(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute("INSERT INTO teams(name, normalized_name) VALUES('Test FC', 'test fc')")
        team_id = conn.execute("SELECT id FROM teams WHERE name='Test FC'").fetchone()[0]
        conn.execute(
            "INSERT INTO runs(run_id, status, started_at) VALUES('TEAM-RUN', 'RUNNING', '2026-10-25T00:00:00+00:00')"
        )
        conn.execute("""
            INSERT INTO research_tasks(run_id, match_id, task_uuid, domain, task_type, description,
                home_team, away_team, competition, scheduled_at)
            VALUES('TEAM-RUN', NULL, 'TEAM-TASK', 'TEAM_PROFILE', 'NEWS_COLLECTION',
                'Profile Test FC', 'Test FC', '', '', '2026-10-25T00:00:00+00:00')
        """)
        task_id = conn.execute("SELECT id FROM research_tasks WHERE task_uuid='TEAM-TASK'").fetchone()[0]

    repo.save_claims_and_evidence("TEAM-RUN", task_id, [{
        "subject": "Test FC", "predicate": "team_profile_fact", "object": "Verified fact",
        "status": "VALID", "confidence": 0.9, "evidence_list": [],
    }])
    repo.save_team_profile(team_id, "2026-10-25T00:00:00+00:00", "TEAM-RUN", [{
        "subject": "Test FC", "predicate": "team_profile_fact", "object": "Verified fact",
        "status": "VALID", "confidence": 0.9, "evidence": [],
    }])

    with sqlite3.connect(db_path) as conn:
        claim = conn.execute("SELECT match_id, claim_text FROM claims").fetchone()
        snapshot = conn.execute("SELECT profile_json FROM team_profile_snapshots WHERE team_id=?", (team_id,)).fetchone()
    assert claim == (None, "Test FC team_profile_fact Verified fact")
    assert '"Verified fact"' in snapshot[0]
