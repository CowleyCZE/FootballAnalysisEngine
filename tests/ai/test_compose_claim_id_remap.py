"""Nález z běhu M943: qwen2.5:3b uvádí claim_id místo evidence_id (295 VALID claimů s evidencí, přesto insufficient_data)."""
import json

from app.workers.ai_worker import AIWorker

CONTEXT = {
    "data_quality": {"score": 0.7, "source_count": 2, "independent_sources": 2, "official_sources": 0,
                     "conflicts": 0, "freshness_score": 0.5, "missing_data": []},
    "claims": [
        {"claim_id": 7, "predicate": "form", "evidence": [{"evidence_id": 501}, {"evidence_id": 502}]},
        {"claim_id": 9, "predicate": "form", "evidence": [{"evidence_id": 777}]},
    ],
    "conflicts": [],
}


def _raw(ids):
    return json.dumps({"conclusion": "Závěr.", "key_factors": [{"factor": "Forma", "importance": 0.6, "evidence_ids": ids}],
                       "uncertainties": []})


def test_valid_evidence_id_is_kept_unchanged():
    result, state = AIWorker._compose_result(_raw([777]), 1, CONTEXT)
    assert state == "VALID" and result.key_factors[0].evidence_ids == [777]
    assert result.uncertainties == []


def test_claim_id_is_mapped_to_that_claims_real_evidence():
    result, state = AIWorker._compose_result(_raw([7]), 1, CONTEXT)
    assert state == "VALID"
    assert result.key_factors[0].evidence_ids == [501, 502]
    assert any("claim_id" in u for u in result.uncertainties)


def test_localized_ids_are_sequential_and_mapped_back_to_real_ids():
    prompt_context, id_map = AIWorker._localize_ids(CONTEXT)
    assert id_map == {1: 501, 2: 502, 3: 777}
    assert all("claim_id" not in c for c in prompt_context["claims"])
    assert [e["evidence_id"] for c in prompt_context["claims"] for e in c["evidence"]] == [1, 2, 3]
    assert CONTEXT["claims"][0]["claim_id"] == 7  # původní kontext se nemění
    result, state = AIWorker._compose_result(_raw([1, 3]), 1, CONTEXT, id_map)
    assert state == "VALID" and result.key_factors[0].evidence_ids == [501, 777]
    result, error = AIWorker._compose_result(_raw([4, 10]), 1, CONTEXT, id_map)
    assert result is None and "AI uvedla evidence_ids" in error


def test_unknown_id_is_still_rejected_and_error_names_counts():
    result, error = AIWorker._compose_result(_raw([123456]), 1, CONTEXT)
    assert result is None
    assert "123456" in error and "3 evidence_id" in error and "2 claim" in error
