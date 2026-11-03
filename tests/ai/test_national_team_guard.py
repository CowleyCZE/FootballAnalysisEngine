"""TODO 13.1 (běh M979): AI napsala „Česká fotbalová reprezentace bude hrát doma proti reprezentaci Rakouska“ v ligovém
zápase. Zmínka o národních týmech v klubovém zápase = fatální halucinace → výstup se zamítne (záložní deterministický závěr)."""
import json

from app.workers.ai_worker import AIWorker, _national_team_mentions

CONTEXT = {
    "match": {"home_team": "SK Artis Brno", "away_team": "Bohemians 1905", "competition": "Chance Liga",
              "scheduled_at": "2026-11-08T14:00:00+00:00"},
    "data_quality": {"score": 0.7, "source_count": 2, "independent_sources": 2, "official_sources": 0,
                     "conflicts": 0, "freshness_score": 0.5, "missing_data": []},
    "claims": [
        {"claim_id": 1, "subject": "Bohemians 1905", "predicate": "availability_status", "object": "Kovařík zraněn",
         "evidence": [{"evidence_id": 10, "excerpt": "Záložník Kovařík je zraněný a chybí."}]},
    ],
    "conflicts": [],
}
FACTOR = {"factor": "Záložník Kovařík je zraněný", "importance": 0.8, "evidence_ids": [10]}


def _raw(conclusion, factors=(FACTOR,), uncertainties=()):
    return json.dumps({"conclusion": conclusion, "key_factors": list(factors), "uncertainties": list(uncertainties)})


def test_mentions_detects_czech_forms_and_english():
    assert _national_team_mentions("Česká reprezentace hraje doma.", "Chance Liga")
    assert _national_team_mentions("Proti reprezentaci Rakouska", "Chance Liga")
    assert _national_team_mentions("národní tým Rakouska", "Chance Liga")
    assert _national_team_mentions("the national team plays", "Chance Liga")
    assert not _national_team_mentions("Bohemians hrají v Brně.", "Chance Liga")


def test_international_competition_is_exempt():
    assert _national_team_mentions("Česká reprezentace hraje.", "Kvalifikace MS 2026") == []
    assert _national_team_mentions("Česká reprezentace hraje.", "Přátelský zápas") == []


def test_empty_competition_is_treated_as_club_match():
    assert _national_team_mentions("Česká reprezentace hraje.", None)


def test_conclusion_with_national_team_is_rejected():
    res, err = AIWorker._compose_result(
        _raw("Česká fotbalová reprezentace bude hrát doma proti reprezentaci Rakouska."), 979, CONTEXT)
    assert res is None and "Halucinace národních týmů" in err
    # opravná iterace se u fatální halucinace nespouští
    assert "klíčový faktor" not in err and "Závěr AI obsahoval" not in err and "JSON Decode Error" not in err


def test_factor_with_national_team_is_rejected():
    res, err = AIWorker._compose_result(
        _raw("Bohemians mají zraněného záložníka.",
             [{"factor": "Reprezentace Rakouska hraje", "importance": 0.5, "evidence_ids": [10]}]), 979, CONTEXT)
    assert res is None and "Halucinace" in err


def test_valid_club_output_still_passes():
    res, err = AIWorker._compose_result(_raw("Bohemians mají zraněného záložníka Kovaříka."), 979, CONTEXT)
    assert res is not None, err


def test_national_team_output_is_accepted_for_international_match():
    ctx = json.loads(json.dumps(CONTEXT))
    ctx["match"]["competition"] = "Kvalifikace MS"
    res, err = AIWorker._compose_result(_raw("Bohemians mají zraněného záložníka, reprezentace to řeší."), 979, ctx)
    assert res is not None, err
