"""TODO 11.20: `Claim.date_source` se ukládá do tabulky `claims` (a migruje do starých DB)."""
import sqlite3

from app.ai.context_builder import ContextBuilder
from app.database.research_repository import ResearchRepository
from app.database.schema import _ensure_column, _migrate_legacy_schema


def _repo_with_task(tmp_path):
    db = str(tmp_path / "t.db")
    repo = ResearchRepository(db)
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO runs(run_id, status, started_at) VALUES('R1','RUNNING','2026-11-02T00:00:00')")
        conn.execute("INSERT INTO teams(name, normalized_name) VALUES('A','a'),('B','b')")
        conn.execute("INSERT INTO matches(home_team_id, away_team_id) VALUES(1,2)")
        cols = [r[1] for r in conn.execute("PRAGMA table_info(research_tasks)")]
        assert "run_id" in cols
        conn.execute(
            "INSERT INTO research_tasks(run_id, match_id, task_uuid, domain, task_type, description, required, priority, "
            "home_team, away_team, competition, scheduled_at, status) "
            "VALUES('R1',1,'u1','ABSENCES_HOME','DISCOVERY','x',1,50,'A','B','L','2026-11-07T14:00:00+00:00','RUNNING')"
        )
    return db, repo


def test_date_source_is_persisted_and_loaded(tmp_path):
    db, repo = _repo_with_task(tmp_path)
    repo.save_claims_and_evidence("R1", 1, [
        {"match_id": 1, "subject": "A", "predicate": "availability_status", "object": "zraněn",
         "normalized_value": "zranen", "confidence": 0.5, "status": "VALID", "date_source": "retrieved_at",
         "evidence_list": [{"source_url": "https://x.cz/a", "text_fragment": "A je zraněn", "published_at": None}]},
        {"match_id": 1, "subject": "A", "predicate": "team_profile_fact", "object": "fakt",
         "normalized_value": "fakt", "confidence": 0.9, "status": "VALID",
         "evidence_list": [{"source_url": "https://x.cz/b", "text_fragment": "fakt", "published_at": None}]},
    ])
    with sqlite3.connect(db) as conn:
        rows = dict(conn.execute("SELECT claim_type, date_source FROM claims").fetchall())
    assert rows == {"availability_status": "retrieved_at", "team_profile_fact": None}

    loaded = ContextBuilder(db_path=db).load_claims_from_db(1)
    by_pred = {c["predicate"]: c["date_source"] for c in loaded}
    assert by_pred["availability_status"] == "retrieved_at"
    assert by_pred["team_profile_fact"] is None


def test_legacy_claims_table_gets_column():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE claims (id INTEGER PRIMARY KEY, claim_text TEXT)")
    _migrate_legacy_schema(conn)
    assert "date_source" in {r[1] for r in conn.execute("PRAGMA table_info(claims)")}
    _ensure_column(conn, "claims", "date_source", "TEXT")  # idempotentní
