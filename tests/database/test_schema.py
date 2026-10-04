import sqlite3

from app.database.schema import SCHEMA_VERSION, initialize_database


def test_initialize_database_contains_canonical_research_schema(tmp_path):
    db = tmp_path / "canonical.db"
    initialize_database(str(db))

    with sqlite3.connect(db) as conn:
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert {"runs", "jobs", "research_tasks", "research_sessions", "claims", "evidence", "system_events"}.issubset(tables)
        assert conn.execute("SELECT value FROM system_info WHERE key='schema_version'").fetchone()[0] == str(SCHEMA_VERSION)


def test_initialize_database_migrates_legacy_matches_and_pipeline_columns(tmp_path):
    db = tmp_path / "legacy.db"
    with sqlite3.connect(db) as conn:
        conn.executescript(
            """
            CREATE TABLE system_info (id INTEGER PRIMARY KEY AUTOINCREMENT, key TEXT UNIQUE, value TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE matches (id INTEGER PRIMARY KEY AUTOINCREMENT, competition TEXT NOT NULL, home_team_id INTEGER NOT NULL, away_team_id INTEGER NOT NULL, scheduled_at TEXT);
            CREATE TABLE jobs (id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT UNIQUE, status TEXT NOT NULL);
            CREATE TABLE pipeline_runs (id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT UNIQUE, state TEXT NOT NULL, started_at TEXT NOT NULL, updated_at TEXT NOT NULL);
            """
        )

    initialize_database(str(db))

    with sqlite3.connect(db) as conn:
        match_columns = {row[1] for row in conn.execute("PRAGMA table_info(matches)")}
        job_columns = {row[1] for row in conn.execute("PRAGMA table_info(jobs)")}
        pipeline_columns = {row[1] for row in conn.execute("PRAGMA table_info(pipeline_runs)")}
        assert {"venue", "status", "season"}.issubset(match_columns)
        assert {"heartbeat_at", "next_attempt_at", "fingerprint"}.issubset(job_columns)
        assert {"cycle", "max_cycles", "finished_at", "error_text"}.issubset(pipeline_columns)
