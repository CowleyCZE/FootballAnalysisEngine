import json
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Optional

from app.database.schema import initialize_database


class JobStore:
    """Canonical SQLite persistence layer for Part 11 orchestration."""

    def __init__(self, db_path: str = "database/football.db"):
        self.db_path = db_path
        self.init_db()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def init_db(self) -> None:
        initialize_database(self.db_path)

    def register_worker(self, worker_id: str, capabilities: Iterable[str], worker_type: str = "generic", metadata: Optional[Dict[str, Any]] = None) -> None:
        now = self.now()
        with self.connect() as conn:
            conn.execute("INSERT INTO workers(worker_id, worker_type, status, capabilities_json, last_heartbeat, metadata_json, registered_at) VALUES(?, ?, 'IDLE', ?, ?, ?, ?) ON CONFLICT(worker_id) DO UPDATE SET worker_type=excluded.worker_type, status='IDLE', capabilities_json=excluded.capabilities_json, last_heartbeat=excluded.last_heartbeat, metadata_json=excluded.metadata_json", (worker_id, worker_type, json.dumps(sorted(set(capabilities))), now, json.dumps(metadata or {}), now))

    def heartbeat(self, worker_id: str, current_job_id: Optional[str] = None) -> None:
        with self.connect() as conn:
            conn.execute("UPDATE workers SET status=?, last_heartbeat=?, current_job_id=? WHERE worker_id=?", ('BUSY' if current_job_id else 'IDLE', self.now(), current_job_id, worker_id))
            if current_job_id:
                conn.execute("UPDATE jobs SET heartbeat_at=? WHERE job_id=? AND worker_id=? AND status IN ('CLAIMED','RUNNING')", (self.now(), current_job_id, worker_id))

    def _event(self, conn: sqlite3.Connection, event_type: str, job_id: Optional[str], worker_id: Optional[str], payload: Dict[str, Any]) -> None:
        run_id = None
        if job_id:
            row = conn.execute("SELECT run_id FROM jobs WHERE job_id=?", (job_id,)).fetchone()
            run_id = row[0] if row else None
        conn.execute("INSERT INTO system_events(event_type,run_id,job_id,worker_id,payload_json,created_at) VALUES(?,?,?,?,?,?)", (event_type, run_id, job_id, worker_id, json.dumps(payload, sort_keys=True), self.now()))

    def create_job(self, job_id: str, job_type: str, match_id: Optional[int], run_id: Optional[str], payload: Dict[str, Any], fingerprint: str, priority: int, max_attempts: int, parent_job_id: Optional[int] = None) -> Optional[str]:
        with self.connect() as conn:
            existing = conn.execute("SELECT job_id FROM jobs WHERE fingerprint=? LIMIT 1", (fingerprint,)).fetchone()
            if existing:
                return None
            if run_id:
                row = conn.execute("SELECT run_id FROM runs WHERE run_id=?", (run_id,)).fetchone()
                if not row:
                    conn.execute(
                        "INSERT INTO runs(run_id,status,started_at,pipeline_version) VALUES(?,?,?,?)",
                        (run_id, "RUNNING", self.now(), "job-store"),
                    )
            conn.execute("INSERT INTO jobs(job_id, run_id, match_id, parent_job_id, job_type, status, priority, payload_json, fingerprint, max_attempts, created_at) VALUES(?,?,?,?,?,'PENDING',?,?,?,?,?)", (job_id, run_id, match_id, parent_job_id, job_type, priority, json.dumps(payload, sort_keys=True), fingerprint, max_attempts, self.now()))
            self._event(conn, "JOB_CREATED", job_id, None, {"job_type": job_type, "fingerprint": fingerprint})
            return job_id

    def mark_blocked(self, job_id: str) -> None:
        with self.connect() as conn:
            changed = conn.execute("UPDATE jobs SET status='BLOCKED' WHERE job_id=? AND status='PENDING'", (job_id,)).rowcount
            if changed:
                self._event(conn, "JOB_BLOCKED", job_id, None, {})

    def claim(self, worker_id: str, capabilities: Iterable[str]) -> Optional[Dict[str, Any]]:
        caps = set(capabilities)
        if not caps:
            return None
        self.register_worker(worker_id, caps)
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            rows = conn.execute("SELECT * FROM jobs WHERE status IN ('PENDING','RETRY') AND (next_attempt_at IS NULL OR next_attempt_at <= ?) AND NOT EXISTS (SELECT 1 FROM job_dependencies d JOIN jobs dep ON dep.id=d.depends_on_job_id WHERE d.job_id=jobs.id AND dep.status!='SUCCESS') ORDER BY priority DESC, id ASC", (self.now(),)).fetchall()
            selected = None
            for row in rows:
                payload = json.loads(row["payload_json"] or "{}")
                required = set(payload.get("capabilities_required") or [])
                if required and not required.issubset(caps):
                    continue
                elif not required and row["job_type"] not in caps and "generic" not in caps:
                    continue
                selected = row
                break
            if not selected:
                conn.commit()
                return None
            now = self.now()
            conn.execute("UPDATE jobs SET status='CLAIMED', worker_id=?, started_at=?, heartbeat_at=?, attempts=attempts+1, next_attempt_at=NULL WHERE id=? AND status IN ('PENDING','RETRY')", (worker_id, now, now, selected['id']))
            conn.execute("UPDATE workers SET status='BUSY', current_job_id=?, last_heartbeat=? WHERE worker_id=?", (selected['job_id'], now, worker_id))
            attempt = int(selected["attempts"]) + 1
            payload = json.loads(selected['payload_json'] or '{}')
            payload["_job_attempt_number"] = attempt
            payload["_job_id"] = selected["job_id"]
            self._event(conn, "JOB_CLAIMED", selected["job_id"], worker_id, {"attempt_number": attempt, "capabilities": sorted(caps)})
            return dict(selected) | {"payload": payload, "attempt_number": attempt}

    def finish(self, job_id: str, worker_id: str, success: bool, result: Optional[Dict[str, Any]] = None, error: Optional[str] = None) -> None:
        now = self.now()
        with self.connect() as conn:
            row = conn.execute("SELECT status, attempts, max_attempts, result_json, worker_id FROM jobs WHERE job_id=?", (job_id,)).fetchone()
            if not row:
                raise KeyError(job_id)
            if row["status"] in {"SUCCESS", "FAILED"}:
                return
            if row["worker_id"] != worker_id:
                return
            if success:
                status, next_attempt = 'SUCCESS', None
            elif row['attempts'] < row['max_attempts']:
                status = 'RETRY'
                delay = min(300, 30 * (2 ** max(0, row['attempts'] - 1)))
                next_attempt = datetime.fromtimestamp(datetime.now(timezone.utc).timestamp() + delay, tz=timezone.utc).isoformat()
            else:
                status, next_attempt = 'FAILED', None
            finished_at = now if status in ('SUCCESS', 'FAILED') else None
            conn.execute("UPDATE jobs SET status=?, result_json=CASE WHEN ? IS NOT NULL THEN ? ELSE result_json END, error_text=?, finished_at=?, next_attempt_at=?, worker_id=NULL WHERE job_id=? AND status NOT IN ('SUCCESS','FAILED') AND worker_id=?", (status, json.dumps(result) if result is not None else None, json.dumps(result) if result is not None else None, error, finished_at, next_attempt, job_id, worker_id))
            conn.execute("UPDATE workers SET status='IDLE', current_job_id=NULL, last_heartbeat=? WHERE worker_id=?", (now, worker_id))
            self._event(conn, "JOB_FINISHED" if status in ('SUCCESS', 'FAILED') else "JOB_RETRY_SCHEDULED", job_id, worker_id, {"status": status, "attempts": int(row["attempts"]), "error": error})

    @staticmethod
    def now() -> str:
        return datetime.now(timezone.utc).isoformat()
