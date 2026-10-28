"""Readiness endpoint počítá se skutečnými job typy pipeline (RESEARCH + STATISTICS)."""
import sqlite3

import pytest
from fastapi.testclient import TestClient

import app.api.server as server_module
from app.database.schema import initialize_database

AUTH = {"X-Worker-Token": "test-secret-token"}


@pytest.fixture
def api_db(tmp_path, monkeypatch):
    db_file = str(tmp_path / "readiness.db")
    monkeypatch.setattr(server_module, "DB_PATH", db_file)
    monkeypatch.setenv("WORKER_API_TOKEN", "test-secret-token")
    initialize_database(db_file)
    with sqlite3.connect(db_file) as conn:
        conn.execute("INSERT INTO teams(id, name, normalized_name) VALUES (1, 'Real Madrid', 'real_madrid'), (2, 'Barcelona', 'barcelona')")
        conn.execute("INSERT INTO competitions(id, name, country) VALUES (1, 'La Liga', 'Spain')")
        conn.execute("INSERT INTO matches(id, competition, competition_id, home_team_id, away_team_id, scheduled_at, status) VALUES (101, 'La Liga', 1, 1, 2, '2026-10-15T18:00:00+00:00', 'RESOLVED')")
    return db_file


def _start(client):
    return client.post("/api/analysis/start", json={"match_id": 101}, headers=AUTH).json()["run_id"]


def test_readiness_not_ready_before_jobs_finish(api_db):
    client = TestClient(server_module.app)
    run_id = _start(client)

    data = client.get(f"/api/analysis/{run_id}/readiness", headers=AUTH).json()

    assert data["ready"] is False
    assert data["required_complete"] is False
    assert data["coverage_score"] == 0.0


def test_readiness_complete_when_research_and_statistics_succeeded(api_db):
    client = TestClient(server_module.app)
    run_id = _start(client)
    with sqlite3.connect(api_db) as conn:
        conn.execute("UPDATE jobs SET status='SUCCESS' WHERE run_id=? AND job_type IN ('RESEARCH','STATISTICS')", (run_id,))
        conn.execute("UPDATE pipeline_runs SET state='ANALYZING' WHERE run_id=?", (run_id,))

    data = client.get(f"/api/analysis/{run_id}/readiness", headers=AUTH).json()

    assert data["required_complete"] is True
    assert data["ready"] is True
    assert data["coverage_score"] == 1.0
    assert data["warnings"] == []


def test_readiness_partial_coverage_counts_only_required_types(api_db):
    client = TestClient(server_module.app)
    run_id = _start(client)
    with sqlite3.connect(api_db) as conn:
        conn.execute("UPDATE jobs SET status='SUCCESS' WHERE run_id=? AND job_type='STATISTICS'", (run_id,))

    data = client.get(f"/api/analysis/{run_id}/readiness", headers=AUTH).json()

    assert data["required_complete"] is False
    assert data["coverage_score"] == 0.5


def test_readiness_unknown_run_is_404(api_db):
    client = TestClient(server_module.app)
    assert client.get("/api/analysis/NOPE/readiness", headers=AUTH).status_code == 404
