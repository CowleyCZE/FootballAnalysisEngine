import sqlite3
import pytest
from datetime import datetime, timedelta, timezone

from app.audit.auditor import AdversarialAuditor
from app.audit.repair_queue import RepairQueue
from app.database.schema import initialize_database


@pytest.fixture
def phase4_db(tmp_path):
    db_file = str(tmp_path / "test_phase4.db")
    initialize_database(db_file)
    return db_file


def test_adversarial_auditor_detects_unsupported_claim_and_cutoff_violation(phase4_db):
    auditor = AdversarialAuditor(db_path=phase4_db)
    now = datetime.now(timezone.utc)
    future_date = (now + timedelta(days=5)).isoformat()
    cutoff_date = now.isoformat()

    ai_analysis = {
        "match_id": 77,
        "status": "complete",
        "key_factors": [
            {"factor": "Hallucinated claim", "evidence_ids": [9999]}
        ]
    }

    claims = [
        {
            "id": 1,
            "subject": "Team A",
            "predicate": "status",
            "object": "good",
            "evidence": [
                {"id": 10, "published_at": future_date}
            ]
        }
    ]

    result = auditor.audit(
        match_id=77,
        ai_run_id="run-77",
        ai_analysis=ai_analysis,
        claims=claims,
        statistics={},
        max_cycles=3,
        current_cycle=1,
        data_cutoff_at=cutoff_date
    )

    assert result["status"] == "RESEARCH_REQUIRED"
    assert len(result["issues"]) >= 2
    issue_types = [i["type"] for i in result["issues"]]
    assert "unsupported_claim" in issue_types
    assert "cutoff_violation" in issue_types


def test_repair_queue_generates_canonical_jobs():
    issues = [
        {"type": "missing_evidence", "severity": "HIGH", "description": "Need absence info", "requires_research": True},
        {"type": "conflicting_evidence", "severity": "CRITICAL", "description": "Verify Player X status", "requires_research": True}
    ]

    jobs = RepairQueue.generate_research_jobs(match_id=77, issues=issues)
    assert len(jobs) == 2
    assert jobs[0]["domain"] == "GENERAL"
    assert jobs[1]["domain"] == "ABSENCES_HOME"
    assert jobs[1]["priority"] == 100


def test_audit_max_cycles_safeguard_prevents_infinite_loop(phase4_db):
    auditor = AdversarialAuditor(db_path=phase4_db)

    ai_analysis = {
        "match_id": 77,
        "status": "complete",
        "key_factors": [
            {"factor": "Unsupported factor", "evidence_ids": []}
        ]
    }

    result = auditor.audit(
        match_id=77,
        ai_run_id="run-loop",
        ai_analysis=ai_analysis,
        claims=[],
        statistics={},
        max_cycles=2,
        current_cycle=2
    )

    assert result["status"] == "UNRESOLVED"
