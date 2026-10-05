import sqlite3
from pathlib import Path
from typing import Union

BASE_DIR = Path(__file__).parent.parent.parent
SCHEMA_PATH = BASE_DIR / "database" / "schema.sql"
DB_PATH = BASE_DIR / "database" / "football.db"

def init_database_schema(target: Union[str, Path, sqlite3.Connection]):
    """
    Inicializuje databázové schéma z schema.sql a provede případné migrace sloupců.
    """
    if isinstance(target, (str, Path)):
        conn = sqlite3.connect(str(target))
        should_close = True
    else:
        conn = target
        should_close = False

    conn.execute("PRAGMA foreign_keys = ON")
    if SCHEMA_PATH.exists():
        with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
            schema_sql = f.read()
        conn.executescript(schema_sql)

    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(jobs)")
    cols = [r[1] for r in cursor.fetchall()]
    if cols:
        add_cols = {
            "job_id": "TEXT",
            "match_id": "INTEGER",
            "run_id": "INTEGER",
            "job_type": "TEXT",
            "status": "TEXT",
            "priority": "INTEGER DEFAULT 50",
            "attempts": "INTEGER DEFAULT 0",
            "max_attempts": "INTEGER DEFAULT 3",
            "worker_id": "TEXT",
            "parent_job_id": "INTEGER",
            "payload_json": "TEXT",
            "result_json": "TEXT",
            "fingerprint": "TEXT",
            "heartbeat_at": "TEXT",
            "error": "TEXT",
            "error_text": "TEXT",
            "created_at": "TEXT",
            "started_at": "TEXT",
            "finished_at": "TEXT",
        }
        for col, col_type in add_cols.items():
            if col not in cols:
                try:
                    cursor.execute(f"ALTER TABLE jobs ADD COLUMN {col} {col_type}")
                except sqlite3.OperationalError:
                    pass

    conn.commit()
    if should_close:
        conn.close()

def get_connection(db_path: Union[str, Path] = DB_PATH) -> sqlite3.Connection:
    connection = sqlite3.connect(str(db_path))
    connection.execute("PRAGMA foreign_keys = ON")
    connection.row_factory = sqlite3.Row
    init_database_schema(connection)
    return connection