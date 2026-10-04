import json
import sqlite3
from datetime import datetime, timezone
import logging

logger = logging.getLogger(__name__)


class PipelineRecovery:
    """Recover abandoned jobs without creating duplicate terminal work."""

    def __init__(self, db_path: str = "database/football.db", timeout_seconds: int = 120):
        self.db_path = db_path
        self.timeout_seconds = timeout_seconds

    @staticmethod
    def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table_name,),
        ).fetchone()
        return row is not None

    def recover_dead_workers_and_jobs(self) -> int:
        now = datetime.now(timezone.utc)
        recovered = 0
        with sqlite3.connect(self.db_path, timeout=30) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")

            has_research_tasks = self._table_exists(conn, "research_tasks")
            has_research_executions = self._table_exists(conn, "research_executions")

            rows = conn.execute(
                "SELECT id, job_id, run_id, attempts, max_attempts, heartbeat_at, worker_id, status "
                "FROM jobs WHERE status IN ('CLAIMED','RUNNING')"
            ).fetchall()

            for job in rows:
                heartbeat = job["heartbeat_at"]
                if not heartbeat:
                    continue
                try:
                    heartbeat_dt = datetime.fromisoformat(heartbeat.replace("Z", "+00:00"))
                except ValueError:
                    continue
                if heartbeat_dt.tzinfo is None:
                    heartbeat_dt = heartbeat_dt.replace(tzinfo=timezone.utc)

                age = (now - heartbeat_dt).total_seconds()
                if age <= self.timeout_seconds:
                    continue

                attempts = int(job["attempts"])
                max_attempts = int(job["max_attempts"])
                if attempts < max_attempts:
                    status = "RETRY"
                    delay = min(300, 30 * (2 ** max(0, attempts - 1)))
                    next_attempt = datetime.fromtimestamp(
                        now.timestamp() + delay, tz=timezone.utc
                    ).isoformat()
                    task_status = "QUEUED"
                else:
                    status = "FAILED"
                    next_attempt = None
                    task_status = "FAILED"

                conn.execute(
                    "UPDATE jobs SET status=?, worker_id=NULL, heartbeat_at=NULL, "
                    "finished_at=?, next_attempt_at=?, error_text=? "
                    "WHERE id=? AND status IN ('CLAIMED','RUNNING')",
                    (
                        status,
                        now.isoformat(),
                        next_attempt,
                        f"Worker heartbeat timeout after {int(age)}s",
                        job["id"],
                    ),
                )

                if has_research_tasks:
                    conn.execute(
                        "UPDATE research_tasks SET status=?, "
                        "attempt_number=MAX(attempt_number, ?), updated_at=? "
                        "WHERE job_id=? AND status='RUNNING'",
                        (task_status, attempts, now.isoformat(), job["job_id"]),
                    )

                if has_research_tasks and has_research_executions and task_status in {"QUEUED", "FAILED"}:
                    conn.execute(
                        """UPDATE research_executions
                           SET status=?, completed_at=?, error_message=?
                           WHERE task_id IN (
                               SELECT id FROM research_tasks WHERE job_id=?
                           ) AND status='RUNNING'""",
                        (
                            "RETRY" if task_status == "QUEUED" else "FAILED",
                            now.isoformat(),
                            f"Worker heartbeat timeout after {int(age)}s",
                            job["job_id"],
                        ),
                    )

                if job["worker_id"]:
                    conn.execute(
                        "UPDATE workers SET status='OFFLINE', current_job_id=NULL, last_heartbeat=? "
                        "WHERE worker_id=?",
                        (now.isoformat(), job["worker_id"]),
                    )

                if self._table_exists(conn, "system_events"):
                    conn.execute(
                        "INSERT INTO system_events(event_type,run_id,job_id,worker_id,payload_json,created_at) "
                        "VALUES(?,?,?,?,?,?)",
                        (
                            "JOB_RECOVERED",
                            job["run_id"],
                            job["job_id"],
                            job["worker_id"],
                            json.dumps(
                                {
                                    "old_status": job["status"],
                                    "new_status": status,
                                    "attempts": attempts,
                                    "heartbeat_age_seconds": int(age),
                                },
                                sort_keys=True,
                            ),
                            now.isoformat(),
                        ),
                    )

                recovered += 1
                logger.warning("Recovered job %s as %s", job["job_id"], status)

        return recovered
