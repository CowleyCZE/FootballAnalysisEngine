"""Testovací harness: jednoduchý worker s ručně dodanými handlery (TODO 7.1).

Dříve `app/jobs/worker.py`. Produkční worker je `app.workers.daemon.WorkerDaemon`
(`scripts/run_worker.py`); tento pomocník slouží jen testům pipeline.
"""
import logging
import sqlite3
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List

from app.jobs.models import JobStatus
from app.jobs.queue import JobQueue

logger = logging.getLogger(__name__)


class BaseWorkerDaemon:
    def __init__(self, worker_id: str, capabilities: List[str], db_path: str = "database/football.db", poll_interval: int = 2):
        self.worker_id = worker_id
        self.capabilities = capabilities
        self.db_path = db_path
        self.poll_interval = poll_interval
        self.queue = JobQueue(db_path=db_path)
        self.register_worker()

    def register_worker(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        now_iso = datetime.now(timezone.utc).isoformat()
        cursor.execute(
            """INSERT INTO workers (worker_id, worker_type, status, last_heartbeat, registered_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(worker_id) DO UPDATE SET status='IDLE', last_heartbeat=excluded.last_heartbeat""",
            (self.worker_id, ",".join(self.capabilities), "IDLE", now_iso, now_iso)
        )
        conn.commit()
        conn.close()

    def process_next_job(self, handlers: Dict[str, Callable[[Dict[str, Any]], Dict[str, Any]]]) -> bool:
        job = self.queue.claim_job(self.worker_id, self.capabilities)
        if not job:
            return False

        job_id = job["job_id"]
        jtype = job["job_type"]
        handler = handlers.get(jtype)

        if not handler:
            self.queue.update_job_status(job_id, JobStatus.FAILED, error=f"No handler registered for {jtype}", worker_id=self.worker_id)
            return True

        self.queue.update_job_status(job_id, JobStatus.RUNNING, worker_id=self.worker_id)
        try:
            self.queue.update_heartbeat(job_id, worker_id=self.worker_id)
            result = handler(job["payload"])
            self.queue.update_job_status(job_id, JobStatus.SUCCESS, result=result, worker_id=self.worker_id)
        except Exception as e:
            logger.error(f"Worker {self.worker_id} failed on job {job_id}: {e}")
            self.queue.update_job_status(job_id, JobStatus.FAILED, error=str(e), worker_id=self.worker_id)

        return True
