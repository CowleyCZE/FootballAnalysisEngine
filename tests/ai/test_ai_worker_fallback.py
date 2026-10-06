import pytest

from app.workers.ai_worker import AIWorker


class FailingOllama:
    def __init__(self, *args, **kwargs):
        pass

    def generate(self, *args, **kwargs):
        raise RuntimeError("Client error '404 Not Found'")


def test_ai_worker_returns_explicit_insufficient_data_on_ollama_failure(monkeypatch):
    monkeypatch.setattr("app.workers.ai_worker.OllamaClient", FailingOllama)

    result = AIWorker.execute({
        "match_id": 123,
        "claims": [{"claim_id": 1, "subject": "Sparta", "predicate": "form", "object": "good"}]
    })

    assert result["match_id"] == 123
    assert result["status"] == "insufficient_data"
    assert result["data_quality"]["score"] == 0.0
    assert result["key_factors"] == []
    assert result["home_team_analysis"] is None
    assert result["away_team_analysis"] is None
    assert result["uncertainties"]
    assert "404" in result["uncertainties"][0]


def test_ai_worker_returns_insufficient_data_when_claims_empty():
    result = AIWorker.execute({"match_id": 123})
    assert result["match_id"] == 123
    assert result["status"] == "insufficient_data"
    assert "claims" in result["data_quality"]["missing_data"][0]


def test_ai_worker_does_not_fabricate_fallback_evidence(monkeypatch):
    monkeypatch.setattr("app.workers.ai_worker.OllamaClient", FailingOllama)

    result = AIWorker.execute({"match_id": 123})

    assert result["key_factors"] == []
    assert result["conflicts_noted"] == []
    assert result["data_quality"]["source_count"] == 0
    assert result["data_quality"]["independent_sources"] == 0
