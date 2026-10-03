import json
import sqlite3
import uuid
import hashlib
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

from app.jobs.repository import JobRepository
from app.jobs.models import JobStatus

class JobQueue:
    def __init__(self, db_path: str = "database/football.db"):
        self.repo = JobRepository(db_path)

    @staticmethod
    def generate_fingerprint(job_type: str, match_id: Optional[int], payload: Dict[str, Any]) -> str:
        raw = f"{job_type}_{match_id}_{json.dumps(payload, sort_keys=True)}"
        return hashlib.sha256(raw.encode('utf-8')).hexdigest()

    def create_job(
        self,
        job_type: str,
        match_id: Optional[int],
        payload: Dict[str, Any],
        priority: int = 50,
        max_attempts: int = 3,
        parent_job_id: Optional[int] = None,
        depends_on_pks: Optional[List[int]] = None
    ) -> Optional[str]:
        fingerprint = self.generate_fingerprint(job_type, match_id, payload)
        conn = self.repo.get_connection()
        cursor = conn.cursor()

        # Ochrana před duplicitními aktivními joby
        cursor.execute(
            "SELECT job_id FROM jobs WHERE fingerprint = ? AND status IN (?, ?, ?, ?)",
            (fingerprint, JobStatus.PENDING, JobStatus.CLAIMED, JobStatus.RUNNING, JobStatus.BLOCKED)
        )
        existing = cursor.fetchone()
        if existing:
            conn.close()
            return None

        job_id = str(uuid.uuid4())
        created_at = datetime.now(timezone.utc).isoformat()
        status = JobStatus.BLOCKED if depends_on_pks else JobStatus.PENDING

        cursor.execute(
            """INSERT INTO jobs (job_id, job_type, match_id, parent_job_id, status, priority, max_attempts, payload_json, fingerprint, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (job_id, job_type, match_id, parent_job_id, status, priority, max_attempts, json.dumps(payload), fingerprint, created_at)
        )
        new_pk = cursor.lastrowid

        if depends_on_pks:
            try:
                for dep_pk in depends_on_pks:
                    self._insert_dependency(conn, new_pk, dep_pk)
            except ValueError:
                conn.rollback()
                conn.close()
                raise

        conn.commit()
        conn.close()
        return job_id

    def _has_path(self, from_id: int, to_id: int, conn: sqlite3.Connection) -> bool:
        visited = set()
        queue = [from_id]
        cursor = conn.cursor()

        while queue:
            curr = queue.pop(0)
            if curr == to_id:
                return True
            if curr in visited:
                continue
            visited.add(curr)

            cursor.execute(
                "SELECT depends_on_job_id FROM job_dependencies WHERE job_id = ?",
                (curr,),
            )
            for row in cursor.fetchall():
                dep = row[0]
                if dep not in visited:
                    queue.append(dep)

        return False

    def _insert_dependency(self, conn: sqlite3.Connection, job_id: int, depends_on_id: int) -> None:
        if job_id == depends_on_id:
            raise ValueError("Deadlock detected: Job cannot depend on itself")
        if self._has_path(from_id=depends_on_id, to_id=job_id, conn=conn):
            raise ValueError("Deadlock detected: Circular dependency")

        conn.execute(
            "INSERT INTO job_dependencies (job_id, depends_on_job_id) VALUES (?, ?)",
            (job_id, depends_on_id),
        )

    def add_dependency(self, job_id: int, depends_on_id: int) -> None:
        conn = self.repo.get_connection()
        try:
            self._insert_dependency(conn, job_id, depends_on_id)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def claim_job(self, worker_id: str, capabilities: List[str]) -> Optional[Dict[str, Any]]:
        conn = self.repo.get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("BEGIN IMMEDIATE")
            placeholders = ",".join(["?"] * len(capabilities))
            query = f"""
                SELECT id, job_id, job_type, match_id, payload_json
                FROM jobs
                WHERE status = ? AND job_type IN ({placeholders})
                ORDER BY priority DESC, id ASC
                LIMIT 1
            """
            cursor.execute(query, [JobStatus.PENDING] + capabilities)
            row = cursor.fetchone()

            if not row:
                conn.commit()
                conn.close()
                return None

            job_pk, job_id, jtype, match_id, payload_json = row["id"], row["job_id"], row["job_type"], row["match_id"], row["payload_json"]
            now_iso = datetime.now(timezone.utc).isoformat()

            cursor.execute(
                "UPDATE jobs SET status = ?, worker_id = ?, started_at = ?, heartbeat_at = ? WHERE id = ?",
                (JobStatus.CLAIMED, worker_id, now_iso, now_iso, job_pk)
            )
            conn.commit()
            conn.close()

            return {
                "id": job_pk,
                "job_id": job_id,
                "job_type": jtype,
                "match_id": match_id,
                "payload": json.loads(payload_json) if payload_json else {}
            }
        except Exception:
            conn.rollback()
            conn.close()
            raise

    def update_job_status(self, job_id: str, status: str, result: Optional[Dict[str, Any]] = None, error: Optional[str] = None):
        conn = self.repo.get_connection()
        cursor = conn.cursor()
        now_iso = datetime.now(timezone.utc).isoformat()

        if status == JobStatus.SUCCESS:
            cursor.execute(
                "UPDATE jobs SET status = ?, result_json = ?, finished_at = ? WHERE job_id = ?",
                (status, json.dumps(result) if result else None, now_iso, job_id)
            )
        elif status in [JobStatus.FAILED, JobStatus.RETRY]:
            cursor.execute(
                "UPDATE jobs SET status = ?, error_text = ?, finished_at = ? WHERE job_id = ?",
                (status, error, now_iso, job_id)
            )
        else:
            cursor.execute("UPDATE jobs SET status = ? WHERE job_id = ?", (status, job_id))

        conn.commit()
        conn.close()

    def update_heartbeat(self, job_id: str):
        conn = self.repo.get_connection()
        cursor = conn.cursor()
        now_iso = datetime.now(timezone.utc).isoformat()
        cursor.execute("UPDATE jobs SET heartbeat_at = ? WHERE job_id = ?", (now_iso, job_id))
        conn.commit()
        conn.close()
