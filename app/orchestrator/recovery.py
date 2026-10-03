import sqlite3
import json
from datetime import datetime, timezone
import logging

logger = logging.getLogger(__name__)

class PipelineRecovery:
    def __init__(self, db_path: str = "database/football.db", timeout_seconds: int = 120):
        self.db_path = db_path
        self.timeout_seconds = timeout_seconds

    def recover_dead_workers_and_jobs(self) -> int:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        now = datetime.now(timezone.utc)
        cursor.execute("SELECT id, job_id, attempts, max_attempts, heartbeat_at FROM jobs WHERE status IN ('RUNNING', 'CLAIMED')")
        running_jobs = cursor.fetchall()

        recovered_count = 0
        for job in running_jobs:
            hb_str = job["heartbeat_at"]
            if not hb_str:
                continue

            hb_dt = datetime.fromisoformat(hb_str.replace("Z", "+00:00"))
            if hb_dt.tzinfo is None:
                hb_dt = hb_dt.replace(tzinfo=timezone.utc)

            age = (now - hb_dt).total_seconds()
            if age > self.timeout_seconds:
                attempts = job["attempts"] + 1
                new_status = "RETRY" if attempts < job["max_attempts"] else "FAILED"
                now_iso = now.isoformat()

                cursor.execute(
                    "UPDATE jobs SET status = ?, attempts = ?, worker_id = NULL, error_text = ? WHERE id = ?",
                    (new_status, attempts, f"Dead worker timeout after {int(age)}s", job["id"])
                )
                recovered_count += 1
                logger.warning(f"Job {job['job_id']} recovered due to timeout. New status: {new_status}")

        conn.commit()
        conn.close()
        return recovered_count
