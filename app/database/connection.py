import sqlite3
from pathlib import Path
from typing import Union

from app.database.schema import initialize_database

BASE_DIR = Path(__file__).parent.parent.parent
DB_PATH = BASE_DIR / "database" / "football.db"


def init_database_schema(target: Union[str, Path, sqlite3.Connection]):
    """Compatibility wrapper around the canonical database initializer."""
    if isinstance(target, (str, Path)):
        initialize_database(str(target))
        return
    conn = target
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript((BASE_DIR / "database" / "schema.sql").read_text(encoding="utf-8"))
    conn.executescript((BASE_DIR / "database" / "research_schema.sql").read_text(encoding="utf-8"))
    conn.commit()


def get_connection(db_path: Union[str, Path] = DB_PATH) -> sqlite3.Connection:
    connection = sqlite3.connect(str(db_path), timeout=30)
    connection.execute("PRAGMA foreign_keys = ON")
    connection.row_factory = sqlite3.Row
    init_database_schema(connection)
    return connection
