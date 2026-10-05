from __future__ import annotations

import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = 4


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()
        is not None
    )


def _ensure_column(
    conn: sqlite3.Connection,
    table: str,
    column: str,
    definition: str,
) -> None:
    if not _table_exists(conn, table):
        return
    columns = {
        row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
    }
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _migrate_legacy_schema(conn: sqlite3.Connection) -> None:
    # Additive migrations for legacy databases.
    for column, definition in (
        ("external_match_id", "TEXT"),
        ("competition_id", "INTEGER"),
        ("season", "TEXT"),
        ("status", "TEXT"),
        ("venue", "TEXT"),
    ):
        _ensure_column(conn, "matches", column, definition)

    for column, definition in (
        ("run_id", "INTEGER"),
        ("match_id", "INTEGER"),
        ("parent_job_id", "INTEGER"),
        ("job_type", "TEXT"),
        ("priority", "INTEGER NOT NULL DEFAULT 50"),
        ("payload_json", "TEXT"),
        ("result_json", "TEXT"),
        ("attempts", "INTEGER NOT NULL DEFAULT 0"),
        ("max_attempts", "INTEGER NOT NULL DEFAULT 3"),
        ("worker_id", "TEXT"),
        ("fingerprint", "TEXT"),
        ("created_at", "TEXT"),
        ("started_at", "TEXT"),
        ("finished_at", "TEXT"),
        ("heartbeat_at", "TEXT"),
        ("next_attempt_at", "TEXT"),
        ("error", "TEXT"),
        ("error_text", "TEXT"),
    ):
        _ensure_column(conn, "jobs", column, definition)

    for column, definition in (
        ("match_id", "INTEGER"),
        ("cycle", "INTEGER NOT NULL DEFAULT 1"),
        ("max_cycles", "INTEGER NOT NULL DEFAULT 3"),
        ("finished_at", "TEXT"),
        ("error_text", "TEXT"),
    ):
        _ensure_column(conn, "pipeline_runs", column, definition)

    for column, definition in (
        ("worker_type", "TEXT"),
        ("capabilities_json", "TEXT"),
        ("status", "TEXT"),
        ("last_heartbeat", "TEXT"),
        ("current_job_id", "TEXT"),
        ("metadata_json", "TEXT"),
    ):
        _ensure_column(conn, "workers", column, definition)

    if _table_exists(conn, "system_info"):
        conn.execute(
            "INSERT INTO system_info(key, value) VALUES('schema_version', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (str(SCHEMA_VERSION),),
        )


def initialize_database(db_path: str) -> None:
    """Initialize the complete canonical schema, including research tables."""
    schema_path = ROOT / "database" / "schema.sql"
    research_schema_path = ROOT / "database" / "research_schema.sql"

    with sqlite3.connect(db_path, timeout=30) as conn:
        conn.execute("PRAGMA foreign_keys = ON")

        # Create/migrate the base schema before dependent indexes/FKs are used.
        _migrate_legacy_schema(conn)
        conn.executescript(schema_path.read_text(encoding="utf-8"))
        conn.executescript(research_schema_path.read_text(encoding="utf-8"))

        # Runtime compatibility objects required by orchestration.
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS system_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                run_id TEXT,
                job_id TEXT,
                worker_id TEXT,
                payload_json TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_system_events_run
                ON system_events(run_id);
            CREATE INDEX IF NOT EXISTS idx_system_events_job
                ON system_events(job_id);
            """
        )

        _migrate_legacy_schema(conn)
        conn.commit()
