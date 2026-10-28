"""Bezdaté důkazy nesmí samy srazit skóre auditu na 0 (běh M594)."""
from app.audit.auditor import AdversarialAuditor


def test_many_undated_evidence_do_not_zero_the_score(tmp_path):
    db = str(tmp_path / "a.db")
    auditor = AdversarialAuditor(db_path=db, log_dir=str(tmp_path / "logs"))
    claims = [{
        "claim_id": 1, "subject": "match_context", "predicate": "rivalry_context", "object": "derby",
        "confidence": 0.6, "status": "VALID",
        "evidence": [{"evidence_id": 1000 + i, "published_at": None, "source_url": "https://x.test"} for i in range(30)],
    }]
    ai = {"status": "complete", "key_factors": [], "uncertainties": [], "conflicts_noted": [],
          "conclusion": "x", "data_quality": {"score": 0.5}}
    res = auditor.audit(1, "ai-1", ai, claims, {}, data_cutoff_at="2026-10-24T22:38:54+00:00")
    undated = [i for i in res["issues"] if i["type"] == "cutoff_violation" and i["severity"] == "MEDIUM"]
    assert len(undated) == 30  # nálezy se neslučují ani nemažou
    assert res["audit_score"] >= 0.3
