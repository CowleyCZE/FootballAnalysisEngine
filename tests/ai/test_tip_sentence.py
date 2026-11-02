"""Závěr AI začíná deterministickou větou s tipem ze statistického modelu (běh M976_e7ab)."""
import json

from app.workers.ai_worker import AIWorker

REAL = "Slovácko má doma špatnou formu, vyhrálo jen jedno ze šesti utkání"
PRED = {"predicted_score": "1-1", "expected_goals": {"home": 1.23, "away": 1.5},
        "probabilities_1x2": {"home_win": 0.31, "draw": 0.254, "away_win": 0.436}}


def _ctx(prediction):
    return {
        "match": {"home_team": "Zlín", "away_team": "Slovácko"},
        "statistics": {"prediction": prediction} if prediction else {},
        "data_quality": {"score": 0.5, "source_count": 1, "independent_sources": 1, "official_sources": 0,
                         "conflicts": 0, "freshness_score": 0.5, "missing_data": []},
        "claims": [{"claim_id": 10, "subject": "Slovácko", "predicate": "profile", "object": REAL,
                    "evidence": [{"evidence_id": 501, "excerpt": REAL}]}],
        "conflicts": [],
    }


RAW = json.dumps({"conclusion": "Slovácko má doma slabší formu.",
                  "key_factors": [{"factor": "Slovácko má doma špatnou formu a vyhrálo jen jedno utkání",
                                   "importance": 0.8, "evidence_ids": [501]}],
                  "uncertainties": []}, ensure_ascii=False)


def test_conclusion_starts_with_tip():
    result, status = AIWorker._compose_result(RAW, 1, _ctx(PRED))
    assert status == "VALID"
    assert result.conclusion.startswith("Statistický model tipuje výsledek 1:1")
    assert "31,0 %" in result.conclusion and "43,6 %" in result.conclusion
    assert result.conclusion.endswith("Slovácko má doma slabší formu.")


def test_no_tip_without_prediction_or_prior_only():
    assert AIWorker._compose_result(RAW, 1, _ctx(None))[0].conclusion == "Slovácko má doma slabší formu."
    prior = dict(PRED, prior_only=True)
    assert AIWorker._compose_result(RAW, 1, _ctx(prior))[0].conclusion == "Slovácko má doma slabší formu."
