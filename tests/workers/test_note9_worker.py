import pytest
from unittest.mock import MagicMock, patch
import os

from scripts.note9_worker import Note9Worker, DEFAULT_CONFIG


def test_note9_worker_init_and_retry_config(monkeypatch):
    monkeypatch.setenv("WORKER_API_TOKEN", "test-secret-token")
    config = dict(DEFAULT_CONFIG)
    worker = Note9Worker(config)

    assert worker.worker_id == "note9-01"
    assert worker.capabilities == ["TEST", "SEARCH", "CRAWL"]
    assert "http://" in worker.session.adapters
    assert "https://" in worker.session.adapters
    assert worker.session.headers["X-Worker-Token"] == "test-secret-token"


def test_note9_worker_missing_token_raises():
    if "WORKER_API_TOKEN" in os.environ:
        del os.environ["WORKER_API_TOKEN"]
    config = dict(DEFAULT_CONFIG)
    with pytest.raises(RuntimeError, match="Chybí WORKER_API_TOKEN"):
        Note9Worker(config)


def test_note9_worker_reports_server_detail_without_token_leak(monkeypatch, capsys):
    monkeypatch.setenv("WORKER_API_TOKEN", "client-secret")
    worker = Note9Worker(dict(DEFAULT_CONFIG) | {"max_retries": 1})
    response = MagicMock()
    response.raise_for_status.side_effect = __import__("requests").HTTPError(
        "503 Server Error", response=MagicMock(status_code=503, json=lambda: {
            "detail": "API token authentication is not configured on the server."
        })
    )
    worker.session.request = MagicMock(return_value=response)

    with pytest.raises(RuntimeError, match="not configured on the server"):
        worker.request("POST", "/api/workers/register")

    assert "client-secret" not in capsys.readouterr().out
