import logging
import os
import time
import threading
from typing import Callable, Dict

from app.jobs.queue import JobQueue
from app.jobs.models import JobStatus
from app.workers.ai_worker import AIWorker
from app.workers.audit_worker import AuditWorker
from app.workers.crawler_worker import CrawlerWorker
from app.workers.research_worker import ResearchWorker
from app.workers.search_worker import SearchWorker
from app.workers.statistics_worker import StatisticsWorker

logger = logging.getLogger(__name__)


class HeartbeatThread(threading.Thread):
    def __init__(self, queue: JobQueue, worker_id: str, job_id: str, interval: float = 15.0):
        super().__init__(daemon=True)
        self.queue = queue
        self.worker_id = worker_id
        self.job_id = job_id
        self.interval = interval
        self.stop_event = threading.Event()

    def run(self):
        while not self.stop_event.is_set():
            self.stop_event.wait(self.interval)
            if not self.stop_event.is_set():
                try:
                    self.queue.store.heartbeat(self.worker_id, self.job_id)
                except Exception as e:
                    logger.warning("Heartbeat thread failed for job %s: %s", self.job_id, e)

    def stop(self):
        self.stop_event.set()


class WorkerDaemon:
    """Pull-based worker shared by Notebook and Note 9.

    A worker asks the database for work instead of receiving pushed tasks. This
    makes temporary device disconnects safe and allows capabilities to differ
    between devices.
    """

    HANDLERS: Dict[str, Callable] = {
        "RESEARCH": ResearchWorker.execute,
        "SEARCH": SearchWorker.execute,
        "CRAWL": CrawlerWorker.execute,
        "STATISTICS": StatisticsWorker.execute,
        "AI_ANALYSIS": AIWorker.execute,
        "AUDIT": AuditWorker.execute,
    }

    def __init__(self, worker_id: str, capabilities: list[str], db_path: str = "database/football.db", poll_interval: float = 2.0):
        self.worker_id = worker_id
        self.capabilities = sorted(set(capabilities))
        self.queue = JobQueue(db_path)
        self.poll_interval = poll_interval
        self.running = True
        self.queue.store.register_worker(worker_id, self.capabilities, metadata={"pid": os.getpid()})

    def run_once(self) -> bool:
        job = self.queue.claim_job(self.worker_id, self.capabilities)
        if not job:
            self.queue.store.heartbeat(self.worker_id)
            return False

        job_id = job["job_id"]
        handler = self.HANDLERS.get(job["job_type"])
        if handler is None:
            self.queue.update_job_status(job_id, JobStatus.FAILED, error=f"No handler for job type {job['job_type']}", worker_id=self.worker_id)
            return True

        hb_thread = HeartbeatThread(self.queue, self.worker_id, job_id, interval=15.0)
        hb_thread.start()

        try:
            self.queue.store.heartbeat(self.worker_id, job_id)
            result = handler(job["payload"])

            res_status = None
            if isinstance(result, dict):
                res_status = str(result.get("status") or "").upper()

            if res_status in ("FAILED", "ERROR"):
                err_msg = result.get("error") or f"Job handler returned status {res_status}"
                self.queue.update_job_status(job_id, JobStatus.FAILED, result=result, error=str(err_msg), worker_id=self.worker_id)
            elif res_status == "RETRY":
                err_msg = result.get("error") or "Job handler requested retry"
                self.queue.update_job_status(job_id, JobStatus.RETRY, result=result, error=str(err_msg), worker_id=self.worker_id)
            else:
                self.queue.update_job_status(job_id, JobStatus.SUCCESS, result=result, worker_id=self.worker_id)
        except Exception as exc:
            logger.exception("Worker %s failed job %s", self.worker_id, job_id)
            self.queue.update_job_status(job_id, JobStatus.RETRY, error=str(exc), worker_id=self.worker_id)
        finally:
            hb_thread.stop()
        return True

    def run_forever(self) -> None:
        logger.info("Worker %s started with capabilities=%s", self.worker_id, self.capabilities)
        try:
            while self.running:
                worked = self.run_once()
                if not worked:
                    time.sleep(self.poll_interval)
        finally:
            self.queue.store.heartbeat(self.worker_id)
            with self.queue.store.connect() as conn:
                conn.execute("UPDATE workers SET status='OFFLINE', current_job_id=NULL WHERE worker_id=?", (self.worker_id,))

    def stop(self) -> None:
        self.running = False
