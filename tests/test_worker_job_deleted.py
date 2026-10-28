"""Worker nesmí spadnout, když je zápas/běh smazán během zpracování jobu (běh M590)."""
from contextlib import contextmanager

from app.workers.daemon import WorkerDaemon


class _Store:
    db_path = ":memory:"

    def heartbeat(self, *a, **k):
        pass

    @contextmanager
    def connect(self):
        class _Conn:
            def execute(self, *a, **k):
                class _R:
                    def fetchone(self):
                        return None

                return _R()

        yield _Conn()


class _Queue:
    store = _Store()

    def claim_job(self, *a, **k):
        return {"job_id": "J1", "job_type": "RESEARCH", "payload": {}}

    def update_job_status(self, job_id, *a, **k):
        raise KeyError(job_id)  # job zmizel (kaskádové smazání zápasu)


def test_worker_survives_job_deleted_during_processing(monkeypatch):
    daemon = WorkerDaemon.__new__(WorkerDaemon)
    daemon.worker_id = "w"
    daemon.capabilities = ["RESEARCH"]
    daemon.queue = _Queue()
    daemon.poll_interval = 0
    daemon.running = True
    monkeypatch.setitem(WorkerDaemon.HANDLERS, "RESEARCH", lambda payload: {"status": "SUCCESS"})

    assert daemon.run_once() is True
