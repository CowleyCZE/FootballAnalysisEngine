import sqlite3
import logging
from app.jobs.models import JobStatus

logger = logging.getLogger(__name__)

class DependencyScheduler:
    def __init__(self, db_path: str = "database/football.db"):
        self.db_path = db_path

    def update_blocked_jobs(self) -> int:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute("SELECT id FROM jobs WHERE status = ?", (JobStatus.BLOCKED,))
        blocked_jobs = cursor.fetchall()

        unblocked_count = 0
        for job in blocked_jobs:
            j_pk = job["id"]
            cursor.execute(
                """SELECT j.status
                   FROM job_dependencies d
                   JOIN jobs j ON d.depends_on_job_id = j.id
                   WHERE d.job_id = ?""",
                (j_pk,)
            )
            deps = cursor.fetchall()
            
            if not deps:
                continue

            if any(d["status"] == JobStatus.FAILED for d in deps):
                cursor.execute("UPDATE jobs SET status = ?, error_text = ? WHERE id = ?", (JobStatus.FAILED, "Dependency failed", j_pk))
            elif all(d["status"] == JobStatus.SUCCESS for d in deps):
                cursor.execute("UPDATE jobs SET status = ? WHERE id = ?", (JobStatus.PENDING, j_pk))
                unblocked_count += 1

        conn.commit()
        conn.close()
        return unblocked_count
