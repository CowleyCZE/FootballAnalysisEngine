"""Běh M976_c93f: věta se skloněným krátkým názvem klubu („Zlína“, „Zlínu“) byla vyřazena jako „jméno bez opory“,
protože v kontextu je „Zlín“ (kmen 4 písmena)."""
import json

from app.workers.ai_worker import AIWorker, _unknown_names, _fold_text

REAL = "Slovácko má doma špatnou formu, vyhrálo jen jedno ze šesti utkání"
CONTEXT = {
    "match": {"home_team": "Zlín", "away_team": "Slovácko"},
    "data_quality": {"score": 0.5, "source_count": 1, "independent_sources": 1, "official_sources": 0,
                     "conflicts": 0, "freshness_score": 0.5, "missing_data": []},
    "claims": [{"claim_id": 10, "subject": "Slovácko", "predicate": "profile", "object": REAL,
                "evidence": [{"evidence_id": 501, "excerpt": REAL}]}],
    "conflicts": [],
}
KNOWN = _fold_text("Zlín Slovácko")


def test_declined_short_club_name_is_known():
    assert _unknown_names("Zápas proti Zlínu rozhodne forma Zlína.", KNOWN) == []


def test_invented_name_still_unknown():
    assert _unknown_names("Zápas rozhodne Lzejka Líška.", KNOWN) != []


def test_conclusion_with_declined_name_is_kept():
    raw = json.dumps({
        "conclusion": "Slovácko pojede do Zlína s horší domácí formou.",
        "key_factors": [{"factor": "Slovácko má doma špatnou formu a vyhrálo jen jedno utkání",
                         "importance": 0.8, "evidence_ids": [501]}],
        "uncertainties": []}, ensure_ascii=False)
    result, status = AIWorker._compose_result(raw, 1, CONTEXT)
    assert status == "VALID"
    assert "Zlína" in result.conclusion


def test_error_lists_dropped_sentence_reasons():
    raw = json.dumps({
        "conclusion": "Rozhodne Lzejka Líška.",
        "key_factors": [{"factor": "Slovácko má doma špatnou formu", "importance": 0.8, "evidence_ids": [501]}],
        "uncertainties": []}, ensure_ascii=False)
    result, error = AIWorker._compose_result(raw, 1, CONTEXT)
    assert result is None
    assert "důvody vyřazení vět" in error and "Lzejka" in error
