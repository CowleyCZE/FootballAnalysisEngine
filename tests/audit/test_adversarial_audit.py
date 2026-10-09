import pytest
import sqlite3
from datetime import datetime, timedelta, timezone

from app.audit.auditor import AdversarialAuditor
from app.audit.consistency import ConsistencyChecker
from app.audit.freshness import FreshnessChecker

def test_statistical_contradiction_and_inconsistency():
    stats = {"wins": 5, "draws": 2, "losses": 2, "matches": 10} # 5+2+2 != 10 (Inconsistency)
    ai_analysis = {"conclusion": "Tým vyhrál 7 z posledních 10 zápasů."} # 7 != 5 (Contradiction)
    claims = []

    issues = ConsistencyChecker.check_statistical_consistency(stats, claims, ai_analysis)
    types = [i["type"] for i in issues]

    assert "statistical_inconsistency" in types
    assert "statistical_contradiction" in types

def test_stale_evidence_detection():
    old_date = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    res = FreshnessChecker.calculate_freshness(old_date, data_type="lineup")
    assert res["freshness_score"] < 0.3

def test_conflicting_evidence_and_job_generation(tmp_path):
    db_file = str(tmp_path / "test_audit.db")
    auditor = AdversarialAuditor(db_path=db_file)

    claims = [
        {"id": 1, "subject": "Player A", "predicate": "status", "object": "injured", "evidence": []},
        {"id": 2, "subject": "Player A", "predicate": "status", "object": "fit", "evidence": []}
    ]
    ai_analysis = {"key_factors": [], "conclusion": "Analyzovano."}

    res = auditor.audit(match_id=100, ai_run_id="run-1", ai_analysis=ai_analysis, claims=claims, statistics={}, data_cutoff_at="2026-10-04T12:00:00Z")

    assert res["status"] == "RESEARCH_REQUIRED"
    assert len(res["research_jobs"]) > 0
    assert res["research_jobs"][0]["job_type"] == "verify_player_availability"

def test_missing_and_unsupported_evidence():
    ai_analysis = {
        "key_factors": [
            {"factor": "Faktor bez důkazů", "evidence_ids": []},
            {"factor": "Faktor s chybějícím ID", "evidence_ids": [999]}
        ]
    }
    available_ids = [1, 2]

    from app.audit.evidence_checker import EvidenceChecker
    issues = EvidenceChecker.check_ai_evidence(ai_analysis, available_ids)
    types = [i["type"] for i in issues]

    assert "missing_evidence" in types
    assert "unsupported_claim" in types

def test_max_cycles_limit(tmp_path):
    db_file = str(tmp_path / "test_audit.db")
    auditor = AdversarialAuditor(db_path=db_file)

    ai_analysis = {
        "key_factors": [
            {"factor": "Neznámý faktor", "evidence_ids": []}
        ]
    }

    res = auditor.audit(
        match_id=200,
        ai_run_id="run-max",
        ai_analysis=ai_analysis,
        claims=[],
        statistics={},
        max_cycles=3,
        current_cycle=3
    )

    assert res["status"] == "UNRESOLVED"
