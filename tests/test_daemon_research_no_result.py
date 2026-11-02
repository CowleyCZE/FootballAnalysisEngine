"""Běh M976_c93f: nepovinná research doména bez výsledku (NO_RESULT/PARTIAL) není FAILED job."""
import pytest

from app.jobs.models import JobStatus
from app.workers.daemon import WorkerDaemon


class _Store:
    db_path = ":memory:"

    def heartbeat(self, *a, **k):
        pass

    def connect(self):
        raise RuntimeError("bez DB")


class _Queue:
    store = _Store()

    def __init__(self, job_type, payload):
        self.job = {"job_id": "J1", "job_type": job_type, "payload": payload}
        self.updates = []

    def claim_job(self, *a, **k):
        return self.job

    def update_job_status(self, job_id, status, **k):
        self.updates.append((status, k.get("result")))


def _run(job_type, payload, result, monkeypatch):
    daemon = WorkerDaemon.__new__(WorkerDaemon)
    daemon.worker_id = "w"
    daemon.capabilities = [job_type]
    daemon.queue = _Queue(job_type, payload)
    daemon.poll_interval = 0
    daemon.running = True
    monkeypatch.setitem(WorkerDaemon.HANDLERS, job_type, lambda p: result)
    try:
        daemon.run_once()
    except RuntimeError:
        pass
    return daemon.queue.updates


@pytest.mark.parametrize("status", ["NO_RESULT", "PARTIAL"])
def test_optional_research_without_result_is_success(status, monkeypatch):
    updates = _run("RESEARCH", {"required": False}, {"status": status, "claims": []}, monkeypatch)
    assert updates[0][0] == JobStatus.SUCCESS
    assert updates[0][1]["status"] == status
    assert updates[0][1]["job_outcome"] == f"ACCEPTED_{status}"


def test_required_research_without_result_still_fails(monkeypatch):
    updates = _run("RESEARCH", {"required": True}, {"status": "NO_RESULT"}, monkeypatch)
    assert updates[0][0] == JobStatus.FAILED


def test_env_restores_old_behaviour(monkeypatch):
    monkeypatch.setenv("FAE_RESEARCH_NO_RESULT_IS_FAILURE", "1")
    updates = _run("RESEARCH", {}, {"status": "NO_RESULT"}, monkeypatch)
    assert updates[0][0] == JobStatus.FAILED


def test_non_research_no_result_still_fails(monkeypatch):
    updates = _run("STATISTICS", {}, {"status": "NO_RESULT"}, monkeypatch)
    assert updates[0][0] == JobStatus.FAILED


@pytest.mark.parametrize("domain", ["ABSENCES_HOME", "ABSENCES_AWAY"])
def test_required_absences_without_result_is_accepted(domain, monkeypatch):
    # Běh M976_e7ab: povinná ABSENCES_HOME s NO_RESULT (žádná ověřená zpráva o absencích) nesmí shodit běh.
    updates = _run("RESEARCH", {"required": True, "domain": domain}, {"status": "NO_RESULT"}, monkeypatch)
    assert updates[0][0] == JobStatus.SUCCESS
    assert updates[0][1]["job_outcome"] == "ACCEPTED_NO_RESULT"


def test_required_absences_partial_still_fails(monkeypatch):
    updates = _run("RESEARCH", {"required": True, "domain": "ABSENCES_HOME"}, {"status": "PARTIAL"}, monkeypatch)
    assert updates[0][0] == JobStatus.FAILED


@pytest.mark.parametrize("domain", ["TEAM_PROFILE_HOME", "TEAM_PROFILE_AWAY"])
def test_required_team_profile_without_result_still_fails(domain, monkeypatch):
    updates = _run("RESEARCH", {"required": True, "domain": domain}, {"status": "NO_RESULT"}, monkeypatch)
    assert updates[0][0] == JobStatus.FAILED
