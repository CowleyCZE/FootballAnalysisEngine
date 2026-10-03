import sqlite3


class JobRepository:

    def __init__(self, db_path: str):
        self.db_path = db_path
        self.init_db()

    def get_connection(self):
        return sqlite3.connect(self.db_path)

    def init_db(self):
        with self.get_connection() as conn:
            cursor = conn.cursor()

            # Vytvoření tabulky jobs, pokud ještě neexistuje
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    match_id TEXT,
                    status TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)

            # Kontrola existujících sloupců v tabulce jobs
            cursor.execute("PRAGMA table_info(jobs);")
            columns = [column[1] for column in cursor.fetchall()]

            # Pokud sloupec match_id chybí (ze starší verze DB), přidáme ho
            if "match_id" not in columns:
                cursor.execute("ALTER TABLE jobs ADD COLUMN match_id TEXT;")

            # Vytvoření indexu nad match_id
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_jobs_match ON jobs(match_id);"
            )

            conn.commit()