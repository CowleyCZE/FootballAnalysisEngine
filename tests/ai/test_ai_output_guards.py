"""TODO 11.27 (běh M976, Zlín – Slovácko, sobota 7. 11. 2026): AI závěr říkal „v neděli“ a faktor „závazky na zápas“
nesouvisel s citovaným důkazem. Deterministické kontroly: den v týdnu a věcná vazba faktoru na důkaz."""
import json

from app.workers.ai_worker import AIWorker

CONTEXT = {
    "match": {"home_team": "Zlín", "away_team": "Slovácko", "scheduled_at": "2026-11-07T14:00:00+00:00"},
    "data_quality": {"score": 0.7, "source_count": 2, "independent_sources": 2, "official_sources": 0,
                     "conflicts": 0, "freshness_score": 0.5, "missing_data": []},
    "claims": [
        {"claim_id": 1, "subject": "Zlín", "predicate": "rivalry_context", "object": "Derby Zlína a Slovácka",
         "evidence": [{"evidence_id": 10, "excerpt": "Nejčastějším výsledkem derby je skóre 3:1."}]},
        {"claim_id": 2, "subject": "Slovácko", "predicate": "availability_status", "object": "Kovařík zraněn",
         "evidence": [{"evidence_id": 20, "excerpt": "Záložník Kovařík je zraněný a chybí."}]},
    ],
    "conflicts": [],
}


def _raw(conclusion, factors):
    return json.dumps({"conclusion": conclusion, "key_factors": factors, "uncertainties": []})


def test_match_weekday_uses_prague_time():
    assert AIWorker._match_weekday(CONTEXT) == 5  # sobota
    late = {"match": {"scheduled_at": "2026-11-07T23:30:00+00:00"}}  # v Praze už neděle 00:30
    assert AIWorker._match_weekday(late) == 6
    assert AIWorker._match_weekday({"match": {}}) is None


def test_wrong_weekday_detection_czech_and_english():
    assert AIWorker._wrong_weekday("Zápas se očekává v neděli.", 5) == 6
    assert AIWorker._wrong_weekday("Hraje se v sobotu.", 5) is None
    assert AIWorker._wrong_weekday("Match on Friday evening", 5) == 4
    assert AIWorker._wrong_weekday("Střední záložník chybí.", 5) is None  # „střed“ není středa
    assert AIWorker._wrong_weekday("Zápas v neděli.", None) is None


def test_conclusion_sentence_with_wrong_weekday_is_removed():
    res, err = AIWorker._compose_result(
        _raw("Derby bývá vyrovnané. Zápas se očekává v neděli.",
             [{"factor": "Nejčastější výsledek derby je skóre 3:1", "importance": 0.8, "evidence_ids": [10]}]), 976, CONTEXT)
    assert res is not None, err
    assert "neděli" not in res.conclusion and "Derby" in res.conclusion
    assert any("dnem v týdnu" in u for u in res.uncertainties)


def test_conclusion_only_wrong_weekday_is_rejected():
    res, err = AIWorker._compose_result(
        _raw("Zápas se očekává v neděli.",
             [{"factor": "Derby", "importance": 0.8, "evidence_ids": [10]}]), 976, CONTEXT)
    assert res is None and "den v týdnu" in err


def test_factor_with_wrong_weekday_is_dropped():
    res, err = AIWorker._compose_result(
        _raw("Derby bývá vyrovnané.", [
            {"factor": "Zápas v neděli", "importance": 0.5, "evidence_ids": [10]},
            {"factor": "Nejčastější výsledek derby je skóre 3:1", "importance": 0.8, "evidence_ids": [10]},
        ]), 976, CONTEXT)
    assert res is not None, err
    assert [f.factor for f in res.key_factors] == ["Nejčastější výsledek derby je skóre 3:1"]


def test_ungrounded_factor_is_dropped_and_grounded_kept():
    res, err = AIWorker._compose_result(
        _raw("Slovácko může chybět Kovařík.", [
            {"factor": "Slovácko má závazky na zápas proti Zlín", "importance": 1.0, "evidence_ids": [20]},
            {"factor": "Kovařík je zraněn", "importance": 0.7, "evidence_ids": [20]},
        ]), 976, CONTEXT)
    assert res is not None, err
    assert [f.factor for f in res.key_factors] == ["Kovařík je zraněn"]
    assert any("věcně nesouvisí" in u for u in res.uncertainties)


def test_only_ungrounded_factor_leads_to_insufficient_data():
    res, err = AIWorker._compose_result(
        _raw("Slovácko má závazky.", [
            {"factor": "Slovácko má závazky na zápas proti Zlín", "importance": 1.0, "evidence_ids": [10]},
        ]), 976, CONTEXT)
    assert res is None and "podložen" in err


def test_grounding_can_be_disabled_for_diagnostics(monkeypatch):
    monkeypatch.setenv("FAE_AI_GROUNDING", "0")
    res, err = AIWorker._compose_result(
        _raw("Slovácko má závazky.", [
            {"factor": "Slovácko má závazky na zápas proti Zlín", "importance": 1.0, "evidence_ids": [10]},
        ]), 976, CONTEXT)
    assert res is not None, err
