"""Běh M976_1b8d: AI vrátila jediný faktor = opsané označení claimu s tabulkovým šumem. Označení se odstraňuje
(ne vyřazuje celý faktor) a tabulkový šum se zachytí už ve filtru vět i v textu claimu."""
import json

import pytest

from app.ai.context_builder import ContextBuilder
from app.research.relevance_filter import is_table_noise, sentence_is_relevant
from app.workers.ai_worker import AIWorker

NOISE = "2026/27 Slovácko StatisticsPldWDLGFGAGDPPGLast 5Home Form603361"
REAL = "Slovácko má doma špatnou formu, vyhrálo jen jedno ze šesti utkání"


@pytest.mark.parametrize("text", [
    NOISE,
    "Slovácko Pld W D L GF GA GD Pts",
    "Last 5 Home Form603361",
    "SlováckoDerbyFCZlínFotbalNovinky",
])
def test_table_noise_is_detected(text):
    assert is_table_noise(text)
    assert not sentence_is_relevant(text)


@pytest.mark.parametrize("text", [
    REAL,
    "Zlín porazil Slovácko 2:1 a v tabulce je o dva body před ním.",
    "V derby se hrálo v sobotu 7. 11. 2026 od 15:00.",
])
def test_normal_sentences_are_not_table_noise(text):
    assert not is_table_noise(text)
    assert sentence_is_relevant(text)


def _context(claim_object):
    return {
        "match": {"home_team": "Zlín", "away_team": "Slovácko"},
        "data_quality": {"score": 0.5, "source_count": 1, "independent_sources": 1, "official_sources": 0,
                         "conflicts": 0, "freshness_score": 0.5, "missing_data": []},
        "claims": [{"claim_id": 10, "subject": "Slovácko", "predicate": "profile", "object": claim_object,
                    "evidence": [{"evidence_id": 501, "excerpt": claim_object}]}],
        "conflicts": [],
    }


def _raw(factor):
    return json.dumps({"conclusion": "Tip zůstává beze změny.",
                       "key_factors": [{"factor": factor, "importance": 0.5, "evidence_ids": [501]}],
                       "uncertainties": []}, ensure_ascii=False)


def test_label_is_stripped_and_real_text_kept():
    result, status = AIWorker._compose_result(_raw(f"Slovácko:profile:{REAL}"), 1, _context(REAL))
    assert status == "VALID"
    assert [f.factor for f in result.key_factors] == [REAL]
    assert any("bez označení" in u for u in result.uncertainties)


def test_label_with_table_noise_is_dropped():
    result, error = AIWorker._compose_result(_raw(f"Slovácko:profile:{NOISE}"), 1, _context(NOISE))
    assert result is None
    assert "tabulkový/UI šum" in error


def test_context_builder_drops_claim_with_noisy_text():
    claims = [
        {"claim_id": 1, "subject": "Slovácko", "predicate": "profile", "object": NOISE,
         "evidence": [{"evidence_id": 1, "text_fragment": REAL}]},
        {"claim_id": 2, "subject": "Slovácko", "predicate": "profile", "object": REAL,
         "evidence": [{"evidence_id": 2, "text_fragment": REAL}]},
    ]
    kept = ContextBuilder._drop_stale_evidence(claims, 730)
    assert [c["claim_id"] for c in kept] == [2]
