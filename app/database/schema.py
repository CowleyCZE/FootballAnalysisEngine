from __future__ import annotations

import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = 2


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _migrate_legacy_schema(conn: sqlite3.Connection) -> None:
    """Apply additive migrations to databases created by older engine versions."""
    _ensure_column(conn, "matches", "venue", "TEXT")
    _ensure_column(conn, "matches", "status", "TEXT")
    _ensure_column(conn, "matches", "season", "TEXT")
    _ensure_column(conn, "jobs", "heartbeat_at", "TEXT")
    _ensure_column(conn, "jobs", "next_attempt_at", "TEXT")
    _ensure_column(conn, "jobs", "fingerprint", "TEXT")
    _ensure_column(conn, "pipeline_runs", "cycle", "INTEGER NOT NULL DEFAULT 1")
    _ensure_column(conn, "pipeline_runs", "max_cycles", "INTEGER NOT NULL DEFAULT 3")
    _ensure_column(conn, "pipeline_runs", "finished_at", "TEXT")
    _ensure_column(conn, "pipeline_runs", "error_text", "TEXT")
    conn.execute(
        "INSERT INTO system_info(key, value) VALUES('schema_version', ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (str(SCHEMA_VERSION),),
    )


def initialize_database(db_path: str) -> None:
    """Create the complete canonical SQLite schema and migrate older databases."""
    schema_path = ROOT / "database" / "schema.sql"
    research_schema_path = ROOT / "database" / "research_schema.sql"

    with sqlite3.connect(db_path, timeout=30) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executescript(schema_path.read_text(encoding="utf-8"))
        conn.executescript(research_schema_path.read_text(encoding="utf-8"))
        _migrate_legacy_schema(conn)
        conn.commit()
