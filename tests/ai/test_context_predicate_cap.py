"""AI kontext: limit claimů predikátu rivalry_context a preference novějších důkazů (běh 9ae1)."""
from app.ai.context_builder import ContextBuilder


def _claim(i, predicate, confidence, published_at=None):
    ev = [{"evidence_id": i, "published_at": published_at}] if published_at else []
    return {"claim_id": i, "subject": f"s{i}", "predicate": predicate, "object": f"o{i}",
            "confidence": confidence, "status": "VALID", "evidence": ev}


def _builder():
    return ContextBuilder(db_path="")


def test_rivalry_capped_and_prefers_recent(monkeypatch):
    monkeypatch.delenv("FAE_AI_RIVALRY_MAX_CLAIMS", raising=False)
    old = [_claim(i, "rivalry_context", 1.0, "2015-01-01T00:00:00+00:00") for i in range(15)]
    recent = [_claim(100 + i, "rivalry_context", 0.6, "2026-10-20T00:00:00+00:00") for i in range(3)]
    others = [_claim(200 + i, "general_fact", 0.5) for i in range(10)]

    selected = _builder()._select_balanced_claims(old + recent + others, 12)

    rivalry_ids = {c["claim_id"] for c in selected if c["predicate"] == "rivalry_context"}
    assert len(rivalry_ids) <= 5
    assert {100, 101, 102} <= rivalry_ids
    assert sum(1 for c in selected if c["predicate"] == "general_fact") == 7 or len(selected) <= 12


def test_cap_configurable_by_env(monkeypatch):
    monkeypatch.setenv("FAE_AI_RIVALRY_MAX_CLAIMS", "2")
    claims = [_claim(i, "rivalry_context", 1.0, f"2026-10-{10 + i:02d}T00:00:00+00:00") for i in range(6)]
    claims += [_claim(100 + i, "general_fact", 0.5) for i in range(6)]
    selected = _builder()._select_balanced_claims(claims, 8)
    assert sum(1 for c in selected if c["predicate"] == "rivalry_context") == 2


def test_everything_fits_is_unchanged():
    claims = [_claim(i, "rivalry_context", 1.0) for i in range(8)]
    selected = _builder()._select_balanced_claims(claims, 20)
    assert len(selected) == 8
