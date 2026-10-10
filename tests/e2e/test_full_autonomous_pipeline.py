import sqlite3
import pytest
from datetime import datetime, timezone
from fastapi.testclient import TestClient

import app.api.server as server_module
from app.orchestrator.orchestrator import MasterOrchestrator
from app.jobs.worker import BaseWorkerDaemon
from app.workers.statistics_worker import StatisticsWorker
from app.workers.ai_worker import AIWorker
from app.workers.audit_worker import AuditWorker
from app.database.schema import initialize_database


@pytest.fixture
def e2e_db(tmp_path, monkeypatch):
    db_file = str(tmp_path / "e2e_football.db")
    monkeypatch.setattr(server_module, "DB_PATH", db_file)
    monkeypatch.setenv("WORKER_API_TOKEN", "test-secret-token")
    initialize_database(db_file)

    conn = sqlite3.connect(db_file)
    conn.execute("INSERT INTO teams(id, name, normalized_name) VALUES (1, 'Liverpool', 'liverpool'), (2, 'Everton', 'everton')")
    conn.execute("INSERT INTO competitions(id, name, country) VALUES (1, 'Premier League', 'England')")
    conn.execute("INSERT INTO matches(id, competition, competition_id, home_team_id, away_team_id, scheduled_at, venue, status) VALUES (500, 'Premier League', 1, 1, 2, '2026-10-25T15:00:00', 'Anfield', 'RESOLVED')")
    conn.commit()
    conn.close()

    return db_file


def mock_research_handler(payload):
    return {
        "status": "SUCCESS",
        "task_id": payload.get("task_id", 1),
        "execution_id": "exec-123",
        "claims": [
            {
                "claim_id": 101,
                "subject": "Liverpool",
                "predicate": "form",
                "object": "unbeaten",
                "confidence": 0.9,
                "status": "VALID",
                "evidence": [{"evidence_id": 1, "source_url": "https://bbc.com/sport", "published_at": "2026-10-24T12:00:00"}]
            }
        ],
        "evidence_count": 1,
        "sources_count": 1,
        "documents_count": 1,
        "conflicts_count": 0,
        "warnings": [],
        "metrics": {}
    }


def mock_ai_handler(payload):
    return {
        "match_id": payload.get("match_id", 500),
        "status": "complete",
        "data_quality": {
            "score": 0.95,
            "source_count": 1,
            "independent_sources": 1,
            "official_sources": 1,
            "conflicts": 0,
            "freshness_score": 0.95,
            "missing_data": []
        },
        "home_team_analysis": {
            "strengths": ["Unbeaten home streak"],
            "weaknesses": [],
            "tactical_notes": []
        },
        "key_factors": [
            {
                "factor": "Liverpool form is strong",
                "importance": 0.9,
                "evidence_ids": [1]
            }
        ],
        "uncertainties": [],
        "conflicts_noted": [],
        "conclusion": "Liverpool v roli favorita."
    }


AUTH_HEADERS = {"X-Worker-Token": "test-secret-token"}


def test_full_autonomous_pipeline_e2e(e2e_db):
    client = TestClient(server_module.app)

    # 1. API Start
    start_resp = client.post("/api/analysis/start", json={"match_id": 500, "data_cutoff_at": "2026-10-25T14:00:00Z"}, headers=AUTH_HEADERS)
    assert start_resp.status_code == 200
    run_id = start_resp.json()["run_id"]
    assert run_id

    orchestrator = MasterOrchestrator(db_path=e2e_db)
    worker = BaseWorkerDaemon(
        worker_id="e2e-worker-01",
        capabilities=["RESEARCH", "STATISTICS", "AI_ANALYSIS", "AUDIT"],
        db_path=e2e_db
    )

    handlers = {
        "RESEARCH": mock_research_handler,
        "STATISTICS": StatisticsWorker.execute,
        "AI_ANALYSIS": mock_ai_handler,
        "AUDIT": AuditWorker.execute,
    }

    # 2. Loop orchestrator tick + worker execution until terminal state or max ticks
    for _ in range(30):
        orchestrator.tick(run_id)
        worker.process_next_job(handlers)

    # 3. Check final run status via API
    status_resp = client.get(f"/api/analysis/{run_id}", headers=AUTH_HEADERS)
    assert status_resp.status_code == 200
    status_data = status_resp.json()
    assert status_data["state"] in ["COMPLETED", "FINALIZING", "UNRESOLVED"]

    # 4. Check final result via API endpoint
    result_resp = client.get(f"/api/analysis/{run_id}/result", headers=AUTH_HEADERS)
    assert result_resp.status_code == 200
    result_data = result_resp.json()
    assert result_data["run_id"] == run_id
    assert result_data["match_id"] == 500


def test_pipeline_missing_data_insufficient_fallback(e2e_db):
    # Test pipeline execution when AI worker returns insufficient_data fallback.
    # Pipeline MUST finish in UNRESOLVED state (never COMPLETED) when required data is missing.
    client = TestClient(server_module.app)
    start_resp = client.post("/api/analysis/start", json={"match_id": 500, "data_cutoff_at": "2026-10-25T14:00:00Z"}, headers=AUTH_HEADERS)
    run_id = start_resp.json()["run_id"]

    orchestrator = MasterOrchestrator(db_path=e2e_db)
    worker = BaseWorkerDaemon(worker_id="e2e-worker-02", capabilities=["RESEARCH", "STATISTICS", "AI_ANALYSIS", "AUDIT"], db_path=e2e_db)

    handlers = {
        "RESEARCH": lambda p: {"status": "NO_RESULT", "claims": [], "evidence_count": 0},
        "STATISTICS": StatisticsWorker.execute,
        "AI_ANALYSIS": AIWorker.execute,
        "AUDIT": AuditWorker.execute,
    }

    for _ in range(20):
        orchestrator.tick(run_id)
        worker.process_next_job(handlers)

    status_resp = client.get(f"/api/analysis/{run_id}", headers=AUTH_HEADERS)
    assert status_resp.status_code == 200
    # Must end in UNRESOLVED, NEVER COMPLETED
    assert status_resp.json()["state"] == "UNRESOLVED"
