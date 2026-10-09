import sqlite3
import pytest
from fastapi.testclient import TestClient

import app.api.server as server_module
from app.database.schema import initialize_database


@pytest.fixture
def api_test_db(tmp_path, monkeypatch):
    db_file = str(tmp_path / "test_api.db")
    monkeypatch.setattr(server_module, "DB_PATH", db_file)
    monkeypatch.setenv("WORKER_API_TOKEN", "test-secret-token")
    initialize_database(db_file)

    conn = sqlite3.connect(db_file)
    conn.execute("INSERT INTO teams(id, name, normalized_name) VALUES (1, 'Real Madrid', 'real_madrid'), (2, 'Barcelona', 'barcelona'), (3, 'Arsenal', 'arsenal'), (4, 'Chelsea', 'chelsea')")
    conn.execute("INSERT INTO competitions(id, name, country) VALUES (1, 'La Liga', 'Spain'), (2, 'Premier League', 'England')")
    conn.execute("INSERT INTO matches(id, competition, competition_id, home_team_id, away_team_id, scheduled_at) VALUES (101, 'La Liga', 1, 1, 2, '2026-10-15 20:00:00')")
    conn.commit()
    conn.close()

    return db_file


AUTH_HEADERS = {"X-Worker-Token": "test-secret-token"}


def test_health_and_root(api_test_db):
    client = TestClient(server_module.app)
    assert client.get("/").status_code == 200
    assert client.get("/api/health").status_code == 200


def test_start_analysis_by_match_id(api_test_db):
    client = TestClient(server_module.app)
    resp = client.post("/api/analysis/start", json={"match_id": 101})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "started"
    assert data["match_id"] == 101
    run_id = data["run_id"]

    status_resp = client.get(f"/api/analysis/{run_id}")
    assert status_resp.status_code == 200
    status_data = status_resp.json()
    assert status_data["match_id"] == 101
    assert status_data["state"] == "DISCOVERY"
    assert status_data["jobs_count"] >= 2


def test_start_analysis_by_request(api_test_db):
    client = TestClient(server_module.app)
    resp = client.post("/api/analysis/start", json={
        "home_team": "Real Madrid",
        "away_team": "Barcelona",
        "competition": "La Liga",
        "scheduled_at": "2026-10-15T20:00:00"
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "DISCOVERY"
    assert data["match_id"] == 101


def test_start_analysis_creates_match_for_verified_teams(api_test_db):
    # If Arsenal and Chelsea exist but match is not in schedule, start analysis must fail as unverified
    client = TestClient(server_module.app)
    resp = client.post("/api/analysis/start", json={
        "home_team": "Arsenal",
        "away_team": "Chelsea",
        "competition": "Premier League",
        "scheduled_at": "2026-11-20T18:00:00"
    })
    assert resp.status_code == 404
    assert "neexistuje v autoritativním rozpisu" in resp.json()["detail"]


def test_start_analysis_rejects_unverified_teams(api_test_db):
    client = TestClient(server_module.app)
    resp = client.post("/api/analysis/start", json={
        "home_team": "FC Fake Team",
        "away_team": "Chelsea",
        "competition": "Premier League",
        "scheduled_at": "2026-11-20T18:00:00"
    })
    assert resp.status_code == 404
    assert "Zápas nelze ověřit" in resp.json()["detail"]


def test_worker_registration_and_job_claim(api_test_db):
    client = TestClient(server_module.app)
    start_resp = client.post("/api/analysis/start", json={"match_id": 101})
    assert start_resp.status_code == 200

    # Unauthenticated should fail with 401
    unauth_resp = client.post("/api/workers/register", json={
        "worker_id": "test-worker-1",
        "worker_name": "notebook",
        "worker_version": "1.0",
        "capabilities": ["RESEARCH", "STATISTICS"]
    })
    assert unauth_resp.status_code == 401

    reg_resp = client.post("/api/workers/register", json={
        "worker_id": "test-worker-1",
        "worker_name": "notebook",
        "worker_version": "1.0",
        "capabilities": ["RESEARCH", "STATISTICS"]
    }, headers=AUTH_HEADERS)
    assert reg_resp.status_code == 200

    claim_resp = client.post("/api/jobs/claim", json={
        "worker_id": "test-worker-1",
        "capabilities": ["RESEARCH", "STATISTICS"]
    }, headers=AUTH_HEADERS)
    assert claim_resp.status_code == 200
    claim_data = claim_resp.json()
    assert claim_data["status"] == "job_assigned"
    job_id = claim_data["job"]["id"]

    result_resp = client.post(f"/api/jobs/{job_id}/result", json={
        "worker_id": "test-worker-1",
        "status": "SUCCESS",
        "result": {"status": "ok"}
    }, headers=AUTH_HEADERS)
    assert result_resp.status_code == 200


def test_job_result_triggers_autonomous_tick(api_test_db):
    client = TestClient(server_module.app)
    start_resp = client.post("/api/analysis/start", json={"match_id": 101})
    run_id = start_resp.json()["run_id"]

    # Claim and finish all discovery jobs
    while True:
        claim_resp = client.post("/api/jobs/claim", json={
            "worker_id": "w1",
            "capabilities": ["generic", "RESEARCH", "STATISTICS"]
        }, headers=AUTH_HEADERS)
        if claim_resp.json()["status"] == "no_job":
            break
        job_id = claim_resp.json()["job"]["id"]
        client.post(f"/api/jobs/{job_id}/result", json={
            "worker_id": "w1",
            "status": "SUCCESS",
            "result": {"evidence": ["sample"]}
        }, headers=AUTH_HEADERS)

    # Pipeline should have advanced past DISCOVERY automatically
    status_resp = client.get(f"/api/analysis/{run_id}")
    assert status_resp.json()["state"] != "DISCOVERY"
