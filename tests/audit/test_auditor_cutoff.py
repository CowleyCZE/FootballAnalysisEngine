import sqlite3
import pytest
from datetime import datetime, timezone
from app.audit.auditor import AdversarialAuditor
from app.database.schema import initialize_database


@pytest.fixture
def auditor(tmp_path):
    db_file = str(tmp_path / "test_audit_cutoff.db")
    initialize_database(db_file)
    with sqlite3.connect(db_file) as conn:
        conn.execute("INSERT INTO teams(id, name, normalized_name) VALUES (1, 'Arsenal', 'arsenal')")
        conn.execute("INSERT INTO teams(id, name, normalized_name) VALUES (2, 'Chelsea', 'chelsea')")
        conn.execute(
            "INSERT INTO matches(id, competition, home_team_id, away_team_id, scheduled_at, status) VALUES (100, 'Premier League', 1, 2, '2026-10-04T15:00:00Z', 'RESOLVED')"
        )
    return AdversarialAuditor(db_path=db_file)


def test_missing_cutoff_no_alternative(auditor):
    res = auditor.audit(
        match_id=999,
        ai_run_id="run-1",
        ai_analysis={"status": "complete", "key_factors": []},
        claims=[],
        statistics={},
        data_cutoff_at=None,
    )
    assert res["status"] == "UNRESOLVED"
    issues = res["issues"]
    assert any(i["type"] == "cutoff_missing" and i["severity"] == "CRITICAL" for i in issues)


def test_missing_cutoff_does_not_infer_from_scheduled_at_or_db(auditor):
    """Auditor MUST NOT fall back to ai_analysis['match']['scheduled_at'] or DB matches.scheduled_at."""
    ai_analysis = {
        "status": "complete",
        "key_factors": [],
        "match": {"match_id": 100, "scheduled_at": "2026-10-04T15:00:00Z"},  # scheduled_at present, cutoff missing
    }
    res = auditor.audit(
        match_id=100,  # match_id 100 exists in DB with scheduled_at
        ai_run_id="run-scheduled-fallback-test",
        ai_analysis=ai_analysis,
        claims=[],
        statistics={},
        data_cutoff_at=None,
    )
    assert res["status"] == "UNRESOLVED"
    assert any(i["type"] == "cutoff_missing" and i["severity"] == "CRITICAL" for i in res["issues"])


def test_missing_cutoff_with_evidence_timestamps(auditor):
    claims = [
        {
            "id": 1,
            "subject": "Arsenal",
            "predicate": "form",
            "object": "good",
            "evidence": [
                {"id": 10, "published_at": "2026-10-04T12:00:00Z"},
                {"id": 11, "published_at": "2026-10-04T14:00:00Z"},
            ],
        }
    ]
    res = auditor.audit(
        match_id=999,
        ai_run_id="run-2",
        ai_analysis={"status": "complete", "key_factors": []},
        claims=claims,
        statistics={},
        data_cutoff_at=None,
    )
    assert res["status"] == "UNRESOLVED"
    assert any(i["type"] == "cutoff_missing" for i in res["issues"])


def test_auditor_does_not_select_latest_evidence_as_cutoff(auditor):
    claims = [
        {
            "id": 1,
            "subject": "Team A",
            "predicate": "news",
            "object": "info",
            "evidence": [
                {"id": 10, "published_at": "2026-10-01T10:00:00Z"},
                {"id": 20, "published_at": "2026-10-05T18:00:00Z"},
            ],
        }
    ]
    res = auditor.audit(
        match_id=999,
        ai_run_id="run-3",
        ai_analysis={"status": "complete", "key_factors": []},
        claims=claims,
        statistics={},
        data_cutoff_at=None,
    )
    assert res["status"] == "UNRESOLVED"
    assert any(i["type"] == "cutoff_missing" for i in res["issues"])


def test_invalid_cutoff_string(auditor):
    res = auditor.audit(
        match_id=999,
        ai_run_id="run-4",
        ai_analysis={"status": "complete", "key_factors": []},
        claims=[],
        statistics={},
        data_cutoff_at="not-a-valid-iso-date",
    )
    assert res["status"] == "UNRESOLVED"
    assert any(i["type"] == "cutoff_missing" for i in res["issues"])


def test_explicit_valid_cutoff_with_before_evidence(auditor):
    cutoff = "2026-10-04T12:00:00Z"
    claims = [
        {
            "id": 1,
            "subject": "Team A",
            "predicate": "status",
            "object": "ok",
            "evidence": [
                {"id": 10, "published_at": "2026-10-04T10:00:00Z"},
            ],
        }
    ]
    res = auditor.audit(
        match_id=999,
        ai_run_id="run-5",
        ai_analysis={"status": "complete", "key_factors": [{"factor": "ok", "evidence_ids": [10]}]},
        claims=claims,
        statistics={},
        data_cutoff_at=cutoff,
    )
    assert not any(i["type"] == "cutoff_violation" for i in res["issues"])
    assert not any(i["type"] == "cutoff_missing" for i in res["issues"])


def test_evidence_published_after_cutoff(auditor):
    cutoff = "2026-10-04T12:00:00Z"
    claims = [
        {
            "id": 1,
            "subject": "Team A",
            "predicate": "status",
            "object": "ok",
            "evidence": [
                {"id": 10, "published_at": "2026-10-04T15:00:00Z"},  # After cutoff
            ],
        }
    ]
    res = auditor.audit(
        match_id=999,
        ai_run_id="run-6",
        ai_analysis={"status": "complete", "key_factors": [{"factor": "ok", "evidence_ids": [10]}]},
        claims=claims,
        statistics={},
        data_cutoff_at=cutoff,
    )
    assert any(i["type"] == "cutoff_violation" and i["severity"] == "CRITICAL" for i in res["issues"])


def test_time_sensitive_evidence_unknown_date(auditor):
    cutoff = "2026-10-04T12:00:00Z"
    claims = [
        {
            "id": 1,
            "subject": "Player A",
            "predicate": "is_injured",
            "object": "yes",
            "evidence": [
                {"id": 10, "published_at": None},  # Unknown publication date
            ],
        }
    ]
    res = auditor.audit(
        match_id=999,
        ai_run_id="run-7",
        ai_analysis={"status": "complete", "key_factors": [{"factor": "injured", "evidence_ids": [10]}]},
        claims=claims,
        statistics={},
        data_cutoff_at=cutoff,
    )
    assert any(i["type"] == "cutoff_violation" for i in res["issues"])


def test_missing_cutoff_blocking_status(auditor):
    res = auditor.audit(
        match_id=999,
        ai_run_id="run-8",
        ai_analysis={"status": "complete", "key_factors": []},
        claims=[],
        statistics={},
        data_cutoff_at=None,
    )
    assert res["status"] != "AUDIT_COMPLETE"
    assert res["status"] == "UNRESOLVED"
