"""Fáze 9 (run M588) – Ollama timeout/kontext a záložní klíče TheSportsDB."""
from urllib.error import HTTPError

import pytest

from app.statistics import history_autofill
from app.statistics.history_autofill import HistoryAutoFiller
from app.workers.ai_worker import AIWorker


class _CapturingOllama:
    last = None

    def __init__(self, *args, **kwargs):
        type(self).last = kwargs

    def generate(self, *args, **kwargs):
        raise RuntimeError("stop")


def _payload(tmp_path):
    return {
        "match_id": 1,
        "db_path": str(tmp_path / "x.db"),
        "data_cutoff_at": "2026-10-23T04:42:42Z",
        "claims": [{"claim_id": 1, "subject": "Jablonec", "predicate": "form", "object": "dobrá", "confidence": 0.9}],
    }


def test_ai_worker_defaults_long_timeout_and_two_retries(monkeypatch, tmp_path):
    monkeypatch.setattr("app.workers.ai_worker.OllamaClient", _CapturingOllama)
    AIWorker.execute(_payload(tmp_path))
    assert _CapturingOllama.last["timeout"] == 300.0
    assert _CapturingOllama.last["max_retries"] == 2


def test_ai_worker_timeout_and_retries_configurable(monkeypatch, tmp_path):
    monkeypatch.setattr("app.workers.ai_worker.OllamaClient", _CapturingOllama)
    monkeypatch.setenv("OLLAMA_TIMEOUT", "45")
    monkeypatch.setenv("OLLAMA_MAX_RETRIES", "4")
    AIWorker.execute(_payload(tmp_path))
    assert _CapturingOllama.last["timeout"] == 45.0
    assert _CapturingOllama.last["max_retries"] == 4


def test_ollama_client_sends_context_and_predict_limits(monkeypatch):
    import httpx
    from app.ai.client import OllamaClient

    seen = {}

    class FakeClient:
        def __init__(self, *a, **k):
            seen["timeout"] = k.get("timeout")

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, json=None):
            seen["payload"] = json

            class R:
                def raise_for_status(self):
                    pass

                def json(self):
                    return {"response": "{}"}
            return R()

    monkeypatch.setattr(httpx, "Client", FakeClient)
    monkeypatch.setenv("OLLAMA_NUM_CTX", "4096")
    monkeypatch.setenv("OLLAMA_NUM_PREDICT", "512")
    assert OllamaClient(timeout=7.0).generate("x") == "{}"
    assert seen["payload"]["options"]["num_ctx"] == 4096
    assert seen["payload"]["options"]["num_predict"] == 512
    assert seen["timeout"] == 7.0


def test_ollama_client_retries_then_raises(monkeypatch):
    import httpx
    from app.ai.client import OllamaClient

    calls = []

    class FailingClient:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, *a, **k):
            calls.append(1)
            raise httpx.ReadTimeout("timed out")

    monkeypatch.setattr(httpx, "Client", FailingClient)
    with pytest.raises(RuntimeError, match="timed out"):
        OllamaClient(max_retries=2).generate("x")
    assert len(calls) == 2


def _http_error(code):
    return HTTPError("https://www.thesportsdb.com", code, "err", {}, None)


def test_thesportsdb_falls_back_to_next_key_on_403(monkeypatch, tmp_path):
    urls = []

    def fake(url, timeout=20.0):
        urls.append(url)
        if "/json/123/" in url:
            raise _http_error(403)
        return {"teams": None}

    monkeypatch.setattr(history_autofill, "_get_json", fake)
    filler = HistoryAutoFiller(db_path=str(tmp_path / "t.db"), cache_dir=tmp_path / "c")
    count, warnings = filler._import_online_results(["Jablonec", "Slavia Praha"], "Chance Liga", "2026-10-23T04:42:42", {})
    assert count == 0
    assert any("/json/123/" in u for u in urls) and any("/json/3/" in u for u in urls)
    assert any("nenalezen" in w for w in warnings)


def test_thesportsdb_all_keys_rejected_gives_clear_error(monkeypatch, tmp_path):
    monkeypatch.setattr(history_autofill, "_get_json", lambda url, timeout=20.0: (_ for _ in ()).throw(_http_error(403)))
    filler = HistoryAutoFiller(db_path=str(tmp_path / "t.db"), cache_dir=tmp_path / "c")
    with pytest.raises(RuntimeError, match="FAE_THESPORTSDB_KEY"):
        filler._import_online_results(["Jablonec"], "Chance Liga", "2026-10-23T04:42:42", {})


def test_thesportsdb_custom_key_is_used_first(monkeypatch, tmp_path):
    urls = []
    monkeypatch.setenv("FAE_THESPORTSDB_KEY", "mykey")
    monkeypatch.setattr(history_autofill, "_get_json", lambda url, timeout=20.0: urls.append(url) or {"teams": None})
    filler = HistoryAutoFiller(db_path=str(tmp_path / "t.db"), cache_dir=tmp_path / "c")
    filler._import_online_results(["Jablonec"], "Chance Liga", "2026-10-23T04:42:42", {})
    assert "/json/mykey/" in urls[0]
