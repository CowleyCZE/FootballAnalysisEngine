import pytest
from datetime import datetime, timedelta, timezone
from app.audit.auditor import AdversarialAuditor

def test_end_to_end_adversarial_audit_loop(tmp_path):
    db_file = str(tmp_path / "e2e_audit.db")
    auditor = AdversarialAuditor(db_path=db_file)

    # 1. Příprava záměrně chybného vstupu (5 problémů)
    stale_date = (datetime.now(timezone.utc) - timedelta(days=20)).isoformat()
    
    match_id = 555
    claims_cycle1 = [
        # Problém 1: Zastaralý zdroj
        {"id": 1, "subject": "Lineup", "predicate": "status", "object": "confirmed", "evidence": [{"id": 10, "published_at": stale_date}]},
        # Problém 2: Konflikt o dostupnosti hráče
        {"id": 2, "subject": "Hráč X", "predicate": "availability", "object": "injured", "evidence": []},
        {"id": 3, "subject": "Hráč X", "predicate": "availability", "object": "healthy", "evidence": []}
    ]
    
    stats_cycle1 = {
        # Problém 3: Logická nesrovnalost statistik (4+2+2 != 10)
        "wins": 4, "draws": 2, "losses": 2, "matches": 10
    }

    ai_analysis_cycle1 = {
        # Problém 4: Nesprávné statistické tvrzení AI
        "conclusion": "Tým vyhrál 7 z posledních 10 zápasů.",
        "key_factors": [
            # Problém 5: Tvrzení zcela bez evidence_ids
            {"factor": "Klíčový faktor bez důkazu", "evidence_ids": []}
        ]
    }

    # RUN 1: Audit odhalí chyby
    audit_run1 = auditor.audit(
        match_id=match_id,
        ai_run_id="ai-run-1",
        ai_analysis=ai_analysis_cycle1,
        claims=claims_cycle1,
        statistics=stats_cycle1,
        max_cycles=3,
        current_cycle=1
    )

    assert len(audit_run1["issues"]) >= 5
    assert audit_run1["status"] == "RESEARCH_REQUIRED"
    assert len(audit_run1["research_jobs"]) > 0

    # SIMULACE RE-ANALÝZY S OPRAVENÝMI DATY
    fresh_date = datetime.now(timezone.utc).isoformat()
    claims_cycle2 = [
        {"id": 1, "subject": "Lineup", "predicate": "status", "object": "confirmed", "evidence": [{"id": 10, "published_at": fresh_date}]},
        {"id": 2, "subject": "Hráč X", "predicate": "availability", "object": "healthy", "evidence": [{"id": 11, "published_at": fresh_date}]}
    ]
    stats_cycle2 = {"wins": 6, "draws": 2, "losses": 2, "matches": 10}
    ai_analysis_cycle2 = {
        "conclusion": "Tým vyhrál 6 z posledních 10 zápasů.",
        "key_factors": [
            {"factor": "Opravený faktor", "evidence_ids": [11]}
        ]
    }

    # RUN 2: Re-audit potvrzuje vyřešení
    audit_run2 = auditor.audit(
        match_id=match_id,
        ai_run_id="ai-run-2",
        ai_analysis=ai_analysis_cycle2,
        claims=claims_cycle2,
        statistics=stats_cycle2,
        max_cycles=3,
        current_cycle=2
    )

    assert audit_run2["status"] == "AUDIT_COMPLETE"
    assert audit_run2["audit_score"] == 1.0
    assert len(audit_run2["issues"]) == 0
