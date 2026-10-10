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
