import hashlib
import json
import uuid
from typing import Any, Dict, List, Optional

from app.jobs.models import JobStatus
from app.jobs.store import JobStore


class JobQueue:
    """Public queue API used by orchestrator and workers.

    All persistence is delegated to JobStore so there is one job model and one
    set of SQLite locking rules across the application.
    """

    def __init__(self, db_path: str = "database/football.db"):
        self.store = JobStore(db_path)

    @staticmethod
    def generate_fingerprint(job_type: str, match_id: Optional[int], payload: Dict[str, Any], run_id: Optional[str] = None) -> str:
        raw = json.dumps(
            {"job_type": job_type, "match_id": match_id, "run_id": run_id, "payload": payload},
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def create_job(
        self,
        job_type: str,
        match_id: Optional[int],
        payload: Dict[str, Any],
        priority: int = 50,
        max_attempts: int = 3,
        parent_job_id: Optional[int] = None,
        depends_on_pks: Optional[List[int]] = None,
        run_id: Optional[str] = None,
    ) -> Optional[str]:
        job_id = str(uuid.uuid4())
        fingerprint = self.generate_fingerprint(job_type, match_id, payload, run_id)
        created = self.store.create_job(
            job_id=job_id,
            job_type=job_type,
            match_id=match_id,
            run_id=run_id,
            payload=payload,
            fingerprint=fingerprint,
            priority=int(priority),
            max_attempts=int(max_attempts),
            parent_job_id=parent_job_id,
        )
        if not created:
            return None

        if depends_on_pks:
            for dep in depends_on_pks:
                self.add_dependency_by_pk(self._job_pk(job_id), int(dep))
            self.store.mark_blocked(job_id)
        return job_id

    def _job_pk(self, job_id: str) -> int:
        with self.store.connect() as conn:
            row = conn.execute("SELECT id FROM jobs WHERE job_id=?", (job_id,)).fetchone()
            if not row:
                raise KeyError(job_id)
            return int(row["id"])

    def _has_path(self, from_id: int, to_id: int, conn) -> bool:
        pending = [from_id]
        visited = set()
        while pending:
            current = pending.pop()
            if current == to_id:
                return True
            if current in visited:
                continue
            visited.add(current)
            rows = conn.execute(
                "SELECT depends_on_job_id FROM job_dependencies WHERE job_id=?", (current,)
            ).fetchall()
            pending.extend(int(row[0]) for row in rows)
        return False

    def add_dependency_by_pk(self, job_id: int, depends_on_id: int) -> None:
        if job_id == depends_on_id:
            raise ValueError("Deadlock detected: job cannot depend on itself")
        with self.store.connect() as conn:
            if self._has_path(depends_on_id, job_id, conn):
                raise ValueError("Deadlock detected: circular dependency")
            conn.execute(
                "INSERT OR IGNORE INTO job_dependencies(job_id, depends_on_job_id) VALUES(?, ?)",
                (int(job_id), int(depends_on_id)),
            )

    def add_dependency(self, job_id: str, depends_on_id: str) -> None:
        if isinstance(job_id, int) and isinstance(depends_on_id, int):
            self.add_dependency_by_pk(job_id, depends_on_id)
            return
        self.add_dependency_by_pk(self._job_pk(str(job_id)), self._job_pk(str(depends_on_id)))

    def claim_job(self, worker_id: str, capabilities: List[str]) -> Optional[Dict[str, Any]]:
        return self.store.claim(worker_id, capabilities)

    def update_job_status(self, job_id: str, status: str, result: Optional[Dict[str, Any]] = None, error: Optional[str] = None, worker_id: Optional[str] = None):
        worker_id = worker_id or "system"
        if status == JobStatus.SUCCESS:
            self.store.finish(job_id, worker_id, True, result=result)
        elif status in (JobStatus.FAILED, JobStatus.RETRY):
            self.store.finish(job_id, worker_id, False, result=result, error=error)
        else:
            with self.store.connect() as conn:
                conn.execute("UPDATE jobs SET status=? WHERE job_id=?", (status, job_id))

    def update_heartbeat(self, job_id: str, worker_id: Optional[str] = None):
        if worker_id:
            self.store.heartbeat(worker_id, job_id)
        else:
            with self.store.connect() as conn:
                conn.execute("UPDATE jobs SET heartbeat_at=? WHERE job_id=?", (self.store.now(), job_id))
