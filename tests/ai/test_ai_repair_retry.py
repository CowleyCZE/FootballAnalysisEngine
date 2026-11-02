"""TODO 11.27 (běh M976_5ca7): malý model vrátil faktory s `evidence_ids: []` → jedna opravná iterace se zpětnou vazbou.
Plus šum z RIVALRY (video přehrávač, e-shop, bonusy sázkovek, Wikipedie reference, popisky zápasů)."""
import json

import pytest

from app.research.relevance_filter import sentence_is_relevant
from app.workers.ai_worker import AIWorker

CONTEXT = {
    "match": {"home_team": "Zlín", "away_team": "Slovácko", "scheduled_at": "2026-11-07T14:00:00+00:00",
              "data_cutoff_at": "2026-10-31T23:45:59+00:00"},
    "data_quality": {"score": 0.7, "source_count": 2, "independent_sources": 2, "official_sources": 0,
                     "conflicts": 0, "freshness_score": 0.5, "missing_data": []},
    "claims": [
        {"claim_id": 1, "subject": "Zlín", "predicate": "rivalry_context", "object": "Derby Zlína a Slovácka",
         "evidence": [{"evidence_id": 10, "excerpt": "Nejčastějším výsledkem derby je skóre 3:1."}]},
    ],
    "conflicts": [],
}

BAD = json.dumps({"conclusion": "Derby bývá vyrovnané.", "uncertainties": [],
                  "key_factors": [{"factor": "Závazky kritického stavu", "importance": 1.0, "evidence_ids": []}]})
GOOD = json.dumps({"conclusion": "Derby bývá vyrovnané.", "uncertainties": [],
                   "key_factors": [{"factor": "Nejčastější výsledek derby je skóre 3:1", "importance": 0.7, "evidence_ids": [1]}]})


class FakeBuilder:
    def __init__(self, *args, **kwargs):
        pass

    def build_context(self, **kwargs):
        return json.loads(json.dumps(CONTEXT))


def _fake_ollama(outputs, prompts):
    class FakeOllama:
        def __init__(self, *args, **kwargs):
            self.model = "fake"

        def generate(self, prompt, **kwargs):
            prompts.append(prompt)
            return outputs[min(len(prompts) - 1, len(outputs) - 1)]

    return FakeOllama


def _run(monkeypatch, outputs):
    prompts = []
    monkeypatch.setattr("app.workers.ai_worker.ContextBuilder", FakeBuilder)
    monkeypatch.setattr("app.workers.ai_worker.OllamaClient", _fake_ollama(outputs, prompts))
    result = AIWorker.execute({"match_id": 976, "data_cutoff_at": "2026-10-31T23:45:59Z"})
    return result, prompts


def test_repair_retry_recovers_after_factor_without_evidence(monkeypatch):
    result, prompts = _run(monkeypatch, [BAD, GOOD])
    assert result["status"] == "complete"
    assert len(prompts) == 2
    assert "ZAMÍTNUTA" in prompts[1] and "[1]" in prompts[1]
    assert result["key_factors"][0]["evidence_ids"] == [10]  # lokální 1 → skutečné DB ID


def test_repair_retry_is_limited_to_one_attempt(monkeypatch):
    result, prompts = _run(monkeypatch, [BAD, BAD, GOOD])
    assert result["status"] == "insufficient_data"
    assert len(prompts) == 2


def test_repair_retry_can_be_disabled(monkeypatch):
    monkeypatch.setenv("FAE_AI_REPAIR_RETRIES", "0")
    result, prompts = _run(monkeypatch, [BAD, GOOD])
    assert result["status"] == "insufficient_data"
    assert len(prompts) == 1


NOISE = [
    "Probeer het later opnieuw.0:000:00 / 4:02Live•Volledige video bekijken••",
    "Nalezeno v produktech () Zobrazit všechny v produktech Nalezeno v kategoriích ()",
    "Free bet builder bets are valid 14 days, only deposits with cards & ApplePay are eligible.",
    "Zlín vs Slovácko Stats & PredictionsZZlín0.14 PPGVSSSlovácko0.57 PPGCzech Republic First League",
    "Millwall vs Derby",
    "Leeds United U18 vs Derby County U18",
    "Yellow & red cards — both teams combined",
    "Banker Pick — Cards",
    'Retrieved from "https://en.wikipedia.org/w/index.php?title=Traditional_derby&oldid=1381156"',
    '↑ "Derby Trnava - Slovan sa odohrá bez divákov".',
    'Unsourced material may be challenged and removed.Find sources: "Traditional derby" – news',
]

REAL = [
    "Zlín vs Slovácko skončilo v minulé sezóně 2:1.",
    "Oba celky mají za sebou 15 derby zápasů, bilance vyznívá pro sobotní hosty ze Zlína.",
    "Před derby fotbalistů Slovácka s Fastavem Zlín si ovšem nemůže být jistý nikdo ničím.",
]


@pytest.mark.parametrize("sentence", NOISE)
def test_m976_5ca7_noise_is_filtered(sentence):
    assert not sentence_is_relevant(sentence)


@pytest.mark.parametrize("sentence", REAL)
def test_real_sentences_stay_relevant(sentence):
    assert sentence_is_relevant(sentence)
