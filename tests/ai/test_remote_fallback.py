"""TODO 11.17 – vzdálený LLM jen jako záloha za lokální Ollamou."""
import json

import httpx
import pytest

from app.ai.remote_client import RemoteLLMClient
from app.database.schema import initialize_database
from app.workers.ai_worker import AIWorker

SECRET = "gsk_test_secret_123"
CUTOFF = "2026-10-03T12:00:00+00:00"

VALID_OUTPUT = json.dumps({
    "conclusion": "Arsenal je v dobré formě.",
    "key_factors": [{"factor": "Forma Arsenalu", "importance": 0.7, "evidence_ids": [501]}],
    "uncertainties": [],
})


class FailingOllama:
    def __init__(self, *args, **kwargs):
        self.model = "fail"

    def generate(self, *args, **kwargs):
        raise RuntimeError("Ollama down 503")


def _payload(db):
    return {
        "match_id": 10,
        "db_path": db,
        "data_cutoff_at": CUTOFF,
        "claims": [{
            "claim_id": 1, "subject": "Arsenal", "predicate": "form", "object": "good", "confidence": 0.9,
            "evidence": [{"evidence_id": 501, "source_url": "https://bbc.com/x", "text_fragment": "Arsenal unbeaten"}],
        }],
        "match": {"match_id": 10, "home_team": "Arsenal", "away_team": "Chelsea", "competition": "Premier League",
                  "data_cutoff_at": CUTOFF},
    }


@pytest.fixture
def db(tmp_path):
    path = str(tmp_path / "ai.db")
    initialize_database(path)
    return path


def _client(handler, **kw):
    return RemoteLLMClient(api_key=SECRET, max_retries=kw.pop("max_retries", 1),
                           transport=httpx.MockTransport(handler), **kw)


def test_remote_client_sends_json_mode_and_returns_content():
    seen = {}

    def handler(request):
        seen["auth"] = request.headers["Authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": "{\"a\": 1}"}}]})

    out = _client(handler).generate("ahoj", system_prompt="sys")
    assert out == "{\"a\": 1}"
    assert seen["auth"] == f"Bearer {SECRET}"
    assert seen["body"]["response_format"] == {"type": "json_object"}
    assert [m["role"] for m in seen["body"]["messages"]] == ["system", "user"]


def test_remote_client_error_never_leaks_key_and_does_not_retry_auth_error(monkeypatch):
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(401, json={"error": f"bad key {SECRET}"})

    monkeypatch.setattr("app.ai.remote_client.time.sleep", lambda *_: None)
    with pytest.raises(RuntimeError) as exc:
        _client(handler, max_retries=3).generate("x")
    assert SECRET not in str(exc.value)
    assert "401" in str(exc.value)
    assert len(calls) == 1


def test_remote_client_retries_rate_limit(monkeypatch):
    responses = [httpx.Response(429), httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})]
    monkeypatch.setattr("app.ai.remote_client.time.sleep", lambda *_: None)
    assert _client(lambda request: responses.pop(0), max_retries=2).generate("x") == "ok"


def test_remote_client_requires_key():
    with pytest.raises(ValueError):
        RemoteLLMClient(api_key="  ")


def test_worker_uses_remote_only_after_local_failure(db, monkeypatch):
    created = []

    class FakeRemote:
        def __init__(self, **kwargs):
            created.append(kwargs)
            self.model = kwargs["model"]

        def generate(self, prompt, require_json=True):
            assert "STRICT DATA CUTOFF" in prompt
            return VALID_OUTPUT

    monkeypatch.setattr("app.workers.ai_worker.OllamaClient", FailingOllama)
    monkeypatch.setattr("app.workers.ai_worker.RemoteLLMClient", FakeRemote)
    monkeypatch.setenv("FAE_LLM_PROVIDER", "groq")
    monkeypatch.setenv("GROQ_API_KEY", SECRET)

    result = AIWorker.execute(_payload(db))

    assert result["status"] == "complete"
    assert result["llm_provider"] == "groq"
    assert result["key_factors"][0]["evidence_ids"] == [501]
    assert len(created) == 1 and created[0]["api_key"] == SECRET


def test_worker_prefers_local_model_and_skips_remote_calls(db, monkeypatch):
    class GoodOllama:
        model = "local"

        def __init__(self, *args, **kwargs):
            pass

        def generate(self, prompt, require_json=True):
            return VALID_OUTPUT

    class ExplodingRemote:
        def __init__(self, **kwargs):
            self.model = "r"

        def generate(self, *args, **kwargs):
            raise AssertionError("vzdálený LLM se nesmí volat, když lokální uspěl")

    monkeypatch.setattr("app.workers.ai_worker.OllamaClient", GoodOllama)
    monkeypatch.setattr("app.workers.ai_worker.RemoteLLMClient", ExplodingRemote)
    monkeypatch.setenv("FAE_LLM_PROVIDER", "groq")
    monkeypatch.setenv("GROQ_API_KEY", SECRET)

    result = AIWorker.execute(_payload(db))
    assert result["status"] == "complete"
    assert result["llm_provider"] == "ollama"


def test_worker_without_provider_setting_never_builds_remote(db, monkeypatch):
    def boom(**kwargs):
        raise AssertionError("vzdálený klient nesmí vzniknout bez FAE_LLM_PROVIDER=groq")

    monkeypatch.setattr("app.workers.ai_worker.OllamaClient", FailingOllama)
    monkeypatch.setattr("app.workers.ai_worker.RemoteLLMClient", boom)
    monkeypatch.setenv("GROQ_API_KEY", SECRET)

    result = AIWorker.execute(_payload(db))
    assert result["status"] == "insufficient_data"
    assert "503" in result["uncertainties"][0]


def test_worker_remote_enabled_without_key_reports_it(db, monkeypatch):
    monkeypatch.setattr("app.workers.ai_worker.OllamaClient", FailingOllama)
    monkeypatch.setenv("FAE_LLM_PROVIDER", "groq")
    monkeypatch.delenv("GROQ_API_KEY", raising=False)

    result = AIWorker.execute(_payload(db))
    assert result["status"] == "insufficient_data"
    assert "GROQ_API_KEY" in result["uncertainties"][0]


def test_worker_both_fail_is_insufficient_without_fabrication_or_key(db, monkeypatch):
    class BadRemote:
        def __init__(self, **kwargs):
            self.model = "r"

        def generate(self, *args, **kwargs):
            return json.dumps({"conclusion": "Nepodložený závěr", "key_factors": [], "uncertainties": []})

    monkeypatch.setattr("app.workers.ai_worker.OllamaClient", FailingOllama)
    monkeypatch.setattr("app.workers.ai_worker.RemoteLLMClient", BadRemote)
    monkeypatch.setenv("FAE_LLM_PROVIDER", "groq")
    monkeypatch.setenv("GROQ_API_KEY", SECRET)

    result = AIWorker.execute(_payload(db))
    assert result["status"] == "insufficient_data"
    assert result["key_factors"] == []
    text = result["uncertainties"][0]
    assert "503" in text and "Vzdálená AI záloha" in text
    assert SECRET not in json.dumps(result)
