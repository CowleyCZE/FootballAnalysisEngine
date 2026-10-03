import sqlite3
import json
from datetime import datetime
from typing import Dict, Any, List, Optional

class ResearchRepository:
    def __init__(self, db_path: str = "database/football.db"):
        self.db_path = db_path
        self._init_tables()

    def get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def _init_tables(self):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS research_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_uuid TEXT NOT NULL UNIQUE,
                run_id INTEGER NOT NULL,
                task_id INTEGER NOT NULL,
                strategy TEXT NOT NULL,
                started_at TEXT NOT NULL,
                completed_at TEXT,
                status TEXT NOT NULL,
                FOREIGN KEY (run_id) REFERENCES analysis_runs(id),
                FOREIGN KEY (task_id) REFERENCES research_tasks(id)
            );
            """)

            cursor.execute("""
            CREATE TABLE IF NOT EXISTS research_queries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                query TEXT NOT NULL,
                query_type TEXT NOT NULL,
                query_hash TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                result_count INTEGER DEFAULT 0,
                FOREIGN KEY (session_id) REFERENCES research_sessions(id)
            );
            """)

            cursor.execute("""
            CREATE TABLE IF NOT EXISTS source_candidates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                url TEXT NOT NULL,
                domain TEXT NOT NULL,
                source_type TEXT,
                source_score REAL,
                selected INTEGER NOT NULL DEFAULT 0,
                rejection_reason TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (session_id) REFERENCES research_sessions(id)
            );
            """)

            cursor.execute("""
            CREATE TABLE IF NOT EXISTS research_executions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                execution_uuid TEXT NOT NULL UNIQUE,
                task_id INTEGER NOT NULL,
                attempt_number INTEGER NOT NULL,
                status TEXT NOT NULL,
                started_at TEXT NOT NULL,
                completed_at TEXT,
                error_message TEXT,
                FOREIGN KEY (task_id) REFERENCES research_tasks(id)
            );
            """)
            conn.commit()

    def create_session(self, session_uuid: str, run_id: int, task_id: int, strategy: str) -> int:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            now = datetime.now().isoformat()
            cursor.execute(
                "INSERT INTO research_sessions (session_uuid, run_id, task_id, strategy, started_at, status) VALUES (?, ?, ?, ?, ?, ?)",
                (session_uuid, run_id, task_id, strategy, now, "RUNNING")
            )
            return cursor.lastrowid

    def save_query(self, session_id: int, query: str, query_type: str, query_hash: str, result_count: int = 0):
        with self.get_connection() as conn:
            conn.execute(
                "INSERT INTO research_queries (session_id, query, query_type, query_hash, result_count) VALUES (?, ?, ?, ?, ?)",
                (session_id, query, query_type, query_hash, result_count)
            )

    def save_source_candidate(self, session_id: int, url: str, domain: str, source_type: str, score: float, selected: bool, rejection_reason: Optional[str] = None):
        with self.get_connection() as conn:
            conn.execute(
                "INSERT INTO source_candidates (session_id, url, domain, source_type, source_score, selected, rejection_reason) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (session_id, url, domain, source_type, score, 1 if selected else 0, rejection_reason)
            )

    def create_execution(self, execution_uuid: str, task_id: int, attempt_number: int) -> int:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            now = datetime.now().isoformat()
            cursor.execute(
                "INSERT INTO research_executions (execution_uuid, task_id, attempt_number, status, started_at) VALUES (?, ?, ?, ?, ?)",
                (execution_uuid, task_id, attempt_number, "RUNNING", now)
            )
            return cursor.lastrowid

    def complete_execution(self, execution_id: int, status: str, error_message: Optional[str] = None):
        with self.get_connection() as conn:
            now = datetime.now().isoformat()
            conn.execute(
                "UPDATE research_executions SET status = ?, completed_at = ?, error_message = ? WHERE id = ?",
                (status, now, error_message, execution_id)
            )

    def save_claims_and_evidence(self, run_id: int, task_id: int, claims: List[Dict[str, Any]]):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            for claim in claims:
                cursor.execute("""
                    INSERT INTO claims (run_id, match_id, task_id, subject, predicate, object, normalized_value, source_date, confidence, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    run_id, claim.get("match_id"), task_id, claim["subject"], claim["predicate"],
                    str(claim["object"]), claim["normalized_value"], claim.get("source_date"),
                    claim.get("confidence", 1.0), claim["status"]
                ))
                claim_id = cursor.lastrowid

                for ev in claim.get("evidence_list", []):
                    cursor.execute("""
                        INSERT INTO evidence (claim_id, document_id, source_url, text_fragment, published_at, retrieved_at)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (
                        claim_id, ev.get("document_id"), ev["source_url"], ev["text_fragment"],
                        ev.get("published_at"), datetime.now().isoformat()
                    ))
            conn.commit()
