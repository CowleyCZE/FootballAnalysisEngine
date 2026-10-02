import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent.parent / "database" / "football.db"

def get_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH)
    # DŮLEŽITÉ: Zapnutí cizích klíčů a sqlite3.Row pro práci s klíči
    connection.execute("PRAGMA foreign_keys = ON")
    connection.row_factory = sqlite3.Row
    return connection