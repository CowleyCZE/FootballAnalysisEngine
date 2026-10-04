import sqlite3
import logging
from app.jobs.models import JobStatus

logger = logging.getLogger(__name__)


class DependencyScheduler:
    """Releases jobs only when all dependencies succeeded.

    Research-task mirroring is optional at the queue layer: a database that only
    contains the canonical job schema remains a valid scheduler database.
    """

    def __init__(self, db_path: str = "database/football.db"):
        self.db_path = db_path

    @staticmethod
    def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table_name,),
        ).fetchone()
        return row is not None

    def update_blocked_jobs(self) -> int:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            has_research_tasks = self._table_exists(conn, "research_tasks")
            blocked_jobs = conn.execute(
                "SELECT id, job_id, status FROM jobs WHERE status=?",
                (JobStatus.BLOCKED,),
            ).fetchall()
            unblocked_count = 0
            for job in blocked_jobs:
                deps = conn.execute(
                    "SELECT j.status FROM job_dependencies d "
                    "JOIN jobs j ON d.depends_on_job_id=j.id "
                    "WHERE d.job_id=?",
                    (job["id"],),
                ).fetchall()
                if not deps:
                    continue

                if any(d["status"] in {JobStatus.FAILED, JobStatus.CANCELLED} for d in deps):
                    conn.execute(
                        "UPDATE jobs SET status=?, error_text=? WHERE id=?",
                        (JobStatus.FAILED, "Dependency failed", job["id"]),
                    )
                    if has_research_tasks:
                        conn.execute(
                            "UPDATE research_tasks SET status='BLOCKED', updated_at=CURRENT_TIMESTAMP "
                            "WHERE job_id=? AND status NOT IN "
                            "('SUCCESS','PARTIAL','NO_RESULT','CONFLICTED','FAILED','BLOCKED')",
                            (job["job_id"],),
                        )
                elif all(d["status"] == JobStatus.SUCCESS for d in deps):
                    conn.execute(
                        "UPDATE jobs SET status=? WHERE id=?",
                        (JobStatus.PENDING, job["id"]),
                    )
                    if has_research_tasks:
                        conn.execute(
                            "UPDATE research_tasks SET status='QUEUED', updated_at=CURRENT_TIMESTAMP "
                            "WHERE job_id=? AND status='BLOCKED'",
                            (job["job_id"],),
                        )
                    unblocked_count += 1
            return unblocked_count
