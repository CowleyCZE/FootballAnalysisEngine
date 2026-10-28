import pytest
from fastapi import HTTPException

import app.api.server as server_module


def test_default_placeholder_token_is_rejected(monkeypatch):
    monkeypatch.setenv("WORKER_API_TOKEN", server_module.PLACEHOLDER_TOKEN)
    monkeypatch.delenv("API_SECRET_TOKEN", raising=False)
    with pytest.raises(HTTPException) as exc:
        server_module.verify_api_auth(server_module.PLACEHOLDER_TOKEN, None)
    assert exc.value.status_code == 503
    assert "init.sh" in exc.value.detail


def test_random_token_is_accepted(monkeypatch):
    monkeypatch.setenv("WORKER_API_TOKEN", "x" * 40)
    assert server_module.verify_api_auth("x" * 40, None) is True


def test_menu_snapshot_header_names_xg_coverage():
    from pathlib import Path
    text = (Path(__file__).resolve().parents[2] / "menu.py").read_text(encoding="utf-8")
    assert "'xG cov.'" in text
