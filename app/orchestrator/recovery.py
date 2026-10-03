import sqlite3
from datetime import datetime, timezone
import logging

logger = logging.getLogger(__name__)


class PipelineRecovery:
    def __init__(self, db_path: str = "database/football.db", timeout_seconds: int = 120):
        self.db_path = db_path
        self.timeout_seconds = timeout_seconds

    def recover_dead_workers_and_jobs(self) -> int:
        now = datetime.now(timezone.utc)
        recovered = 0
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            rows = conn.execute(
                "SELECT id, job_id, attempts, max_attempts, heartbeat_at, worker_id FROM jobs WHERE status IN ('CLAIMED','RUNNING')"
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
                    next_attempt = datetime.fromtimestamp(now.timestamp() + delay, tz=timezone.utc).isoformat()
                else:
                    status = "FAILED"
                    next_attempt = None

                conn.execute(
                    """
                    UPDATE jobs
                    SET status=?, worker_id=NULL, heartbeat_at=NULL, finished_at=?,
                        next_attempt_at=?, error_text=?
                    WHERE id=?
                    """,
                    (status, now.isoformat(), next_attempt, f"Worker heartbeat timeout after {int(age)}s", job["id"]),
                )
                if job["worker_id"]:
                    conn.execute(
                        "UPDATE workers SET status='OFFLINE', current_job_id=NULL WHERE worker_id=?",
                        (job["worker_id"],),
                    )
                recovered += 1
                logger.warning("Recovered job %s as %s", job["job_id"], status)
        return recovered
