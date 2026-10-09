from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from app.database.schema import initialize_database


class ResearchRepository:
    """Canonical persistence boundary for research tasks and provenance."""

    TASK_STATUSES = {"PLANNED", "QUEUED", "RUNNING", "SUCCESS", "PARTIAL", "NO_RESULT", "CONFLICTED", "FAILED", "BLOCKED"}
    TERMINAL_TASK_STATUSES = {"SUCCESS", "PARTIAL", "NO_RESULT", "CONFLICTED", "FAILED", "BLOCKED"}

    def __init__(self, db_path: str = "database/football.db"):
        self.db_path = db_path
        self._init_tables()

    def get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _init_tables(self) -> None:
        initialize_database(self.db_path)

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def bind_job(self, task_id: int, job_id: str) -> None:
        with self.get_connection() as conn:
            conn.execute("UPDATE research_tasks SET job_id=?, status=CASE WHEN status IN ('PLANNED','QUEUED') THEN 'QUEUED' ELSE status END, updated_at=? WHERE id=?", (job_id, self._now(), int(task_id)))

    def mark_task_failed(self, task_id: int, error_message: str) -> None:
        with self.get_connection() as conn:
            now = self._now()
            conn.execute("UPDATE research_tasks SET status='FAILED', updated_at=? WHERE id=?", (now, int(task_id)))
            conn.execute("UPDATE research_sessions SET status='FAILED', completed_at=? WHERE task_id=? AND status='RUNNING'", (now, int(task_id)))

    def mark_task_running(self, task_id: int, attempt_number: int) -> None:
        with self.get_connection() as conn:
            row = conn.execute("SELECT status FROM research_tasks WHERE id=?", (int(task_id),)).fetchone()
            if not row:
                raise KeyError(task_id)
            if row["status"] in self.TERMINAL_TASK_STATUSES:
                raise RuntimeError(f"Research task {task_id} is already terminal: {row['status']}")
            conn.execute("UPDATE research_tasks SET status='RUNNING', attempt_number=?, updated_at=? WHERE id=?", (int(attempt_number), self._now(), int(task_id)))

    def get_task(self, task_id: int) -> Optional[sqlite3.Row]:
        with self.get_connection() as conn:
            return conn.execute("SELECT * FROM research_tasks WHERE id=?", (int(task_id),)).fetchone()

    def start_task_execution(self, task_id: int, attempt_number: Optional[int] = None) -> int:
        now = self._now()
        execution_uuid = hashlib.sha256(f"{task_id}:{now}".encode("utf-8")).hexdigest()
        with self.get_connection() as conn:
            row = conn.execute("SELECT attempt_number, status FROM research_tasks WHERE id=?", (int(task_id),)).fetchone()
            if not row:
                raise KeyError(task_id)
            attempt = int(attempt_number or row["attempt_number"] or 1)
            if row["status"] in self.TERMINAL_TASK_STATUSES:
                raise RuntimeError(f"Research task {task_id} is already terminal: {row['status']}")
            conn.execute("UPDATE research_tasks SET status='RUNNING', attempt_number=?, updated_at=? WHERE id=?", (attempt, now, int(task_id)))
            cur = conn.execute("INSERT INTO research_executions(execution_uuid, task_id, attempt_number, status, started_at) VALUES(?,?,?,?,?)", (execution_uuid, int(task_id), attempt, "RUNNING", now))
            return int(cur.lastrowid)

    def finish_task_execution(self, task_id: int, execution_id: int, status: str, error_message: Optional[str] = None) -> None:
        if status not in self.TASK_STATUSES:
            raise ValueError(f"Unsupported research task status: {status}")
        now = self._now()
        with self.get_connection() as conn:
            execution = conn.execute("SELECT status FROM research_executions WHERE id=? AND task_id=?", (int(execution_id), int(task_id))).fetchone()
            if not execution:
                raise KeyError(f"execution {execution_id} for task {task_id}")
            conn.execute("UPDATE research_executions SET status=?, completed_at=?, error_message=? WHERE id=?", (status, now, error_message, int(execution_id)))
            conn.execute("UPDATE research_tasks SET status=?, updated_at=? WHERE id=?", (status, now, int(task_id)))
            conn.execute("UPDATE research_sessions SET status=?, completed_at=? WHERE task_id=? AND status='RUNNING'", (status, now, int(task_id)))

    def create_session(self, session_uuid: str, run_id: int, task_id: int, strategy: str) -> int:
        now = self._now()
        with self.get_connection() as conn:
            run = conn.execute("SELECT run_id FROM runs WHERE id=?", (int(run_id),)).fetchone()
            if not run:
                raise KeyError(f"run {run_id}")
            # research_sessions historically stores the canonical run string FK.
            cur = conn.execute("INSERT INTO research_sessions(session_uuid, run_id, task_id, strategy, started_at, status) VALUES (?, ?, ?, ?, ?, 'RUNNING')", (session_uuid, run["run_id"], int(task_id), strategy, now))
            return int(cur.lastrowid)

    def save_query(self, session_id: int, query: str, query_type: str, query_hash: str, result_count: int = 0) -> None:
        with self.get_connection() as conn:
            conn.execute("INSERT INTO research_queries(session_id, query, query_type, query_hash, result_count) VALUES (?, ?, ?, ?, ?)", (session_id, query, query_type, query_hash, int(result_count)))

    def save_source_candidate(self, session_id: int, url: str, domain: str, source_type: Optional[str], score: float, selected: bool, rejection_reason: Optional[str] = None) -> None:
        with self.get_connection() as conn:
            conn.execute("INSERT INTO source_candidates(session_id, url, domain, source_type, source_score, selected, rejection_reason) VALUES (?, ?, ?, ?, ?, ?, ?)", (session_id, url, domain, source_type, float(score), 1 if selected else 0, rejection_reason))

    def create_execution(self, execution_uuid: str, task_id: int, attempt_number: int) -> int:
        now = self._now()
        with self.get_connection() as conn:
            cur = conn.execute("INSERT INTO research_executions(execution_uuid, task_id, attempt_number, status, started_at) VALUES (?, ?, ?, 'RUNNING', ?)", (execution_uuid, int(task_id), int(attempt_number), now))
            return int(cur.lastrowid)

    def complete_execution(self, execution_id: int, status: str, error_message: Optional[str] = None) -> None:
        with self.get_connection() as conn:
            row = conn.execute("SELECT task_id FROM research_executions WHERE id=?", (execution_id,)).fetchone()
        if not row:
            raise KeyError(execution_id)
        self.finish_task_execution(int(row["task_id"]), execution_id, status, error_message)

    @staticmethod
    def _content_hash(url: str, text: str) -> str:
        return hashlib.sha256(f"{url}\n{text}".encode("utf-8")).hexdigest()

    def _ensure_source(self, conn: sqlite3.Connection, url: str, source_type: Optional[str]) -> int:
        domain = urlparse(url).netloc.lower()
        row = conn.execute("SELECT id FROM sources WHERE domain=?", (domain,)).fetchone()
        if row:
            return int(row["id"])
        cur = conn.execute("INSERT INTO sources(domain, name, source_type, priority, active) VALUES (?, ?, ?, 50, 1)", (domain, domain, source_type))
        return int(cur.lastrowid)

    def _ensure_document(self, conn: sqlite3.Connection, url: str, text: str, published_at: Optional[str], document_id: Optional[int] = None) -> int:
        if document_id is not None and conn.execute("SELECT 1 FROM documents WHERE id=?", (int(document_id),)).fetchone():
            return int(document_id)
        canonical_url = url.split("#", 1)[0]
        content_hash = self._content_hash(url, text)
        row = conn.execute("SELECT id FROM documents WHERE content_hash=? LIMIT 1", (content_hash,)).fetchone()
        if row:
            return int(row["id"])
        source_id = self._ensure_source(conn, url, None)
        cur = conn.execute("INSERT INTO documents(source_id, url, canonical_url, content_hash, title, published_at, retrieved_at, content_type, content_length) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (source_id, url, canonical_url, content_hash, None, published_at, self._now(), "text/html", len(text)))
        return int(cur.lastrowid)

    def save_claims_and_evidence(self, run_id: int, task_id: int, claims: List[Dict[str, Any]]) -> None:
        with self.get_connection() as conn:
            task_row = conn.execute("SELECT match_id FROM research_tasks WHERE id=?", (int(task_id),)).fetchone()
            default_match_id = int(task_row["match_id"]) if task_row else None
            for claim in claims:
                object_value = str(claim.get("object", ""))
                subject = str(claim.get("subject", ""))
                predicate = str(claim.get("predicate", ""))
                normalized = str(claim.get("normalized_value", object_value))
                status = str(claim.get("status", "UNVERIFIED"))
                claim_text = f"{subject} {predicate} {object_value}".strip()
                cur = conn.execute("INSERT INTO claims(run_id, match_id, claim_text, claim_type, normalized_claim, status, confidence, valid_from) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (int(run_id), claim.get("match_id", default_match_id), claim_text, predicate or None, normalized, status, float(claim.get("confidence", 1.0)), claim.get("source_date")))
                claim_id = int(cur.lastrowid)
                for ev in claim.get("evidence_list", []):
                    url = str(ev.get("source_url", ""))
                    fragment = str(ev.get("text_fragment", ""))
                    document_id = self._ensure_document(conn, url, fragment, ev.get("published_at"), ev.get("document_id"))
                    ev_cur = conn.execute("INSERT INTO evidence(document_id, evidence_type, quoted_text, extracted_value, locator, extraction_method, confidence) VALUES (?, 'TEXT', ?, ?, ?, 'research_engine', ?)", (document_id, fragment, object_value, url, float(claim.get("confidence", 1.0))))
                    evidence_id = int(ev_cur.lastrowid)
                    conn.execute("INSERT OR IGNORE INTO claim_evidence(claim_id, evidence_id, relationship, weight) VALUES (?, ?, 'SUPPORTS', ?)", (claim_id, evidence_id, float(claim.get("confidence", 1.0))))
