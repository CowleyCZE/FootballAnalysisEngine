"""TODO 5.3 – `config/crawler.yaml` se skutečně načítá v HTTPClient a EngineCrawler."""
import asyncio

import httpx
import pytest

from app.crawler import http_client as http_client_module
from app.crawler.config import CrawlerSettings, DEFAULT_CONFIG_PATH, load_crawler_settings
from app.crawler.crawler import EngineCrawler
from app.crawler.http_client import HTTPClient


def test_repo_config_is_loaded():
    assert DEFAULT_CONFIG_PATH.exists()
    s = load_crawler_settings()
    assert s.timeout_seconds == 20
    assert s.connect_timeout_seconds == 10
    assert s.max_retries == 3
    assert s.max_redirects == 5
    assert s.user_agent == "FootballAnalysisEngine/1.0"
    assert s.rate_limit_interval_seconds == 2


def test_custom_values_and_invalid_values_fall_back(tmp_path):
    cfg = tmp_path / "crawler.yaml"
    cfg.write_text(
        "crawler:\n  timeout_seconds: 7\n  max_retries: 0\n  user_agent: '  '\n"
        "  max_content_size_mb: abc\n  rate_limit:\n    interval_seconds: 0.5\n  javascript:\n    enabled: false\n",
        encoding="utf-8",
    )
    s = load_crawler_settings(cfg)
    assert s.timeout_seconds == 7
    assert s.max_retries == 3            # neplatné → výchozí
    assert s.user_agent == "FootballAnalysisEngine/1.0"
    assert s.max_content_size_mb == 10   # neplatné → výchozí
    assert s.rate_limit_interval_seconds == 0.5
    assert s.javascript_enabled is False


def test_missing_or_broken_file_gives_defaults(tmp_path):
    assert load_crawler_settings(tmp_path / "neexistuje.yaml") == CrawlerSettings()
    broken = tmp_path / "broken.yaml"
    broken.write_text("crawler: [unclosed", encoding="utf-8")
    assert load_crawler_settings(broken) == CrawlerSettings()


def test_http_client_uses_config_and_explicit_args_win():
    cfg = CrawlerSettings(timeout_seconds=9, max_retries=2, user_agent="CfgUA/2")
    c = HTTPClient(settings=cfg)
    assert (c.timeout, c.max_retries, c.user_agent) == (9, 2, "CfgUA/2")
    c2 = HTTPClient(user_agent="Explicit/1", timeout=3, max_retries=1, settings=cfg)
    assert (c2.timeout, c2.max_retries, c2.user_agent) == (3, 1, "Explicit/1")


def test_engine_crawler_wires_rate_limit_and_user_agent():
    crawler = EngineCrawler()
    assert crawler.http_client.user_agent == crawler.settings.user_agent
    assert crawler.rate_limiter.interval_seconds == crawler.settings.rate_limit_interval_seconds


def _patch_async_client(monkeypatch, handler, captured):
    real = httpx.AsyncClient

    def factory(*args, **kwargs):
        captured.update(kwargs)
        return real(*args, transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(http_client_module.httpx, "AsyncClient", factory)


def test_fetch_passes_config_to_httpx(monkeypatch):
    captured = {}
    _patch_async_client(monkeypatch, lambda req: httpx.Response(200, text="<html>ok</html>"), captured)
    cfg = CrawlerSettings(timeout_seconds=8, connect_timeout_seconds=4, max_redirects=2,
                          follow_redirects=False, user_agent="CfgUA/3")
    result = asyncio.run(HTTPClient(settings=cfg).fetch("https://example.com/"))
    assert result.success
    assert captured["max_redirects"] == 2
    assert captured["follow_redirects"] is False
    assert captured["headers"]["User-Agent"] == "CfgUA/3"
    assert captured["timeout"].read == 8 and captured["timeout"].connect == 4


def test_fetch_rejects_too_large_content_without_retry(monkeypatch):
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        return httpx.Response(200, content=b"x" * 2048)

    _patch_async_client(monkeypatch, handler, {})
    cfg = CrawlerSettings(max_content_size_mb=0.001)  # ≈ 1 kB
    result = asyncio.run(HTTPClient(settings=cfg).fetch("https://example.com/"))
    assert not result.success
    assert "too large" in result.error.lower()
    assert calls["n"] == 1
