import sqlite3
from app.database.connection import init_database_schema

class JobRepository:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.init_db()

    def get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def init_db(self):
        init_database_schema(self.db_path)