"""Běh M976_a388: AI si vymyslela jméno („Lzejka Líška“) a GENERAL přinesla rozpisy mládežnických lig."""
import json

import pytest

from app.research.relevance_filter import sentence_is_relevant
from app.workers.ai_worker import AIWorker

REAL = "Slovácko má doma špatnou formu, vyhrálo jen jedno ze šesti utkání"
CONTEXT = {
    "match": {"home_team": "Zlín", "away_team": "Slovácko"},
    "data_quality": {"score": 0.5, "source_count": 1, "independent_sources": 1, "official_sources": 0,
                     "conflicts": 0, "freshness_score": 0.5, "missing_data": []},
    "claims": [{"claim_id": 10, "subject": "Slovácko", "predicate": "profile", "object": REAL,
                "evidence": [{"evidence_id": 501, "excerpt": REAL}]}],
    "conflicts": [],
}


def _raw(conclusion, factor):
    return json.dumps({"conclusion": conclusion,
                       "key_factors": [{"factor": factor, "importance": 0.9, "evidence_ids": [501]}],
                       "uncertainties": []}, ensure_ascii=False)


def test_invented_name_in_factor_and_conclusion_is_rejected():
    text = "Lzejka Líška byl povolán na zápas, Slovácko má doma špatnou formu"
    result, error = AIWorker._compose_result(_raw("Lzejka Líška byl povolán na zápas.", text), 1, CONTEXT)
    assert result is None
    assert "jméno bez opory" in error


def test_known_names_pass():
    result, status = AIWorker._compose_result(
        _raw("Zlín hraje doma proti Slovácku.", "Slovácko má doma špatnou formu, vyhrálo jen jedno utkání"), 1, CONTEXT)
    assert status == "VALID"


@pytest.mark.parametrize("text", [
    "10.13:15VIKTORIA PLZEŇ - fotbal  -  SK Dynamo Č.",
    "pá13:15MFK Karviná  -  FC ZlínFotbal1.Celostátní liga dorostu U 17",
    "<iframe width=\"1280\" height=\"720\" src=\"//embed.tvcom.cz/x\"",
])
def test_youth_schedule_noise_is_filtered(text):
    assert not sentence_is_relevant(text)
