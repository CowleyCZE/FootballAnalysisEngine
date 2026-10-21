"""TODO 4.3 – jedna implementace ConflictDetector sdílená auditem a researchem."""
import app.audit.conflict_detector as audit_cd
import app.research.conflict_detector as research_cd


def test_audit_reexports_the_research_implementation():
    assert audit_cd.ConflictDetector is research_cd.ConflictDetector
    assert audit_cd.EXCLUSIVE_PREDICATES is research_cd.EXCLUSIVE_PREDICATES


def test_audit_detects_conflict_in_exclusive_predicate():
    claims = [
        {"id": 1, "subject": "Patrik Schick", "predicate": "availability_status", "object": "UNAVAILABLE"},
        {"id": 2, "subject": "patrik schick", "predicate": "availability_status", "object": "FIT"},
    ]
    issues = audit_cd.ConflictDetector.detect_conflicts(claims)
    assert len(issues) == 1
    assert issues[0]["type"] == "conflicting_evidence"
    assert issues[0]["claim_ids"] == [1, 2]
    assert issues[0]["requires_research"] is True


def test_free_text_predicates_and_equal_values_are_not_conflicts():
    claims = [
        {"id": 1, "subject": "Sparta", "predicate": "team_form", "object": "vyhrála"},
        {"id": 2, "subject": "Sparta", "predicate": "team_form", "object": "prohrála"},
        {"id": 3, "subject": "Jan Kuchta", "predicate": "availability_status", "object": "FIT"},
        {"id": 4, "subject": "Jan Kuchta", "predicate": "availability_status", "object": "fit"},
    ]
    assert audit_cd.ConflictDetector.detect_conflicts(claims) == []
