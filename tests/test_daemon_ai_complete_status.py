"""AI_ANALYSIS se stavem „complete“ (schéma AnalysisResult) musí být job SUCCESS, ne FAILED (běh M594)."""
from app.jobs.models import JobStatus
from app.workers.daemon import WorkerDaemon


class _Store:
    db_path = ":memory:"

    def heartbeat(self, *a, **k):
        pass

    def connect(self):
        raise RuntimeError("bez DB")  # advance_run se přeskočí


class _Queue:
    store = _Store()

    def __init__(self):
        self.updates = []

    def claim_job(self, *a, **k):
        return {"job_id": "J1", "job_type": "AI_ANALYSIS", "payload": {}}

    def update_job_status(self, job_id, status, **k):
        self.updates.append(status)


def _run(result, monkeypatch):
    daemon = WorkerDaemon.__new__(WorkerDaemon)
    daemon.worker_id = "w"
    daemon.capabilities = ["AI_ANALYSIS"]
    daemon.queue = _Queue()
    daemon.poll_interval = 0
    daemon.running = True
    monkeypatch.setitem(WorkerDaemon.HANDLERS, "AI_ANALYSIS", lambda payload: result)
    try:
        daemon.run_once()
    except RuntimeError:
        pass
    return daemon.queue.updates


def test_ai_complete_status_marks_job_success(monkeypatch):
    assert _run({"status": "complete", "match_id": 1}, monkeypatch) == [JobStatus.SUCCESS]


def test_unknown_status_still_fails(monkeypatch):
    assert _run({"status": "weird"}, monkeypatch) == [JobStatus.FAILED]
