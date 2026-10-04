from __future__ import annotations

import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def initialize_database(db_path: str) -> None:
    schema_path = ROOT / "database" / "schema.sql"
    research_schema_path = ROOT / "database" / "research_schema.sql"

    with sqlite3.connect(db_path, timeout=30) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executescript(schema_path.read_text(encoding="utf-8"))
        conn.executescript(research_schema_path.read_text(encoding="utf-8"))
        conn.commit()
