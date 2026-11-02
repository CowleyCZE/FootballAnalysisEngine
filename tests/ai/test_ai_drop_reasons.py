"""TODO 11.27 (běh M976_fe22): AI `insufficient_data` bez viditelné příčiny – chyba nyní uvádí důvody vyřazení faktorů."""
import json

import pytest

from app.research.relevance_filter import sentence_is_relevant
from app.workers.ai_worker import AIWorker

CONTEXT = {
    "match": {"home_team": "Zlín", "away_team": "Slovácko", "scheduled_at": "2026-11-07T14:00:00+00:00"},
    "data_quality": {"score": 0.7, "source_count": 2, "independent_sources": 2, "official_sources": 0,
                     "conflicts": 0, "freshness_score": 0.5, "missing_data": []},
    "claims": [
        {"claim_id": 1, "subject": "Zlín", "predicate": "rivalry_context", "object": "Derby Zlína a Slovácka",
         "evidence": [{"evidence_id": 10, "excerpt": "Nejčastějším výsledkem derby je skóre 3:1."}]},
    ],
    "conflicts": [],
}


def _raw(factors):
    return json.dumps({"conclusion": "Derby bývá vyrovnané.", "key_factors": factors, "uncertainties": []})


def test_error_lists_why_every_factor_was_dropped():
    res, err = AIWorker._compose_result(
        _raw([
            {"factor": "Slovácko má závazky na zápas proti Zlín", "importance": 1.0, "evidence_ids": [10]},
            {"factor": "Hraje se v neděli", "importance": 0.5, "evidence_ids": [10]},
            {"factor": "Výborná forma", "importance": 0.5, "evidence_ids": [999]},
        ]), 976, CONTEXT)
    assert res is None
    assert "důvody vyřazení" in err
    assert "věcně nesouvisí" in err
    assert "den v týdnu" in err
    assert "neexistující evidence_id" in err or "nemá platný odkaz" in err


NOISE_M976_FE22 = [
    "PřihlášeníPřihlášení Zaslat zapomenuté heslo Ještě nemám účet, chci se RegistrovatDalší mo",
    "Antigua & Barbuda Dominican Republic Northern Ireland",
    "Yellow and red cards both count.",
    "Under 3.53 or fewer cards — best for low-stakes or lenient-referee fixtures",
    "Over 4.55 or more cards — typically derby or high-stakes fixtures",
    "Over vs Under cards — when to pick each",
    "Which fixtures produce the most cards?",
    "Both teams' cards count toward the total.",
    "Card betting markets are based on the total number of yellow and red cards shown during a match.",
    "Over/Under total corners — same structure as cards but based on set-piece frequency.",
]

REAL = [
    "„Derby je vždycky výzva, vyhraje ten, kdo se lépe připraví a koncentruje.“",
    "Ale v derby favorit často nevyhrává.",
    "Oba celky mají za sebou 15 derby zápasů, bilance vyznívá pro sobotní hosty ze Zlína.",
]


@pytest.mark.parametrize("sentence", NOISE_M976_FE22)
def test_m976_fe22_noise_is_filtered(sentence):
    assert not sentence_is_relevant(sentence)


@pytest.mark.parametrize("sentence", REAL)
def test_real_derby_sentences_stay_relevant(sentence):
    assert sentence_is_relevant(sentence)
