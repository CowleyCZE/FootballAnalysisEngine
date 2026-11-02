"""TODO 11.27: crawler nestahuje netextový obsah (např. `.exe` z wemod CDN) – typ se ověří před čtením těla."""
import asyncio

import httpx
import pytest

from app.crawler import http_client as http_client_module
from app.crawler.config import CrawlerSettings
from app.crawler.http_client import HTTPClient, is_text_content_type


def _patch_async_client(monkeypatch, handler):
    real = httpx.AsyncClient

    def factory(*args, **kwargs):
        return real(*args, transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(http_client_module.httpx, "AsyncClient", factory)


@pytest.mark.parametrize("value,expected", [
    (None, True),
    ("", True),
    ("text/html; charset=utf-8", True),
    ("TEXT/HTML", True),
    ("application/xhtml+xml", True),
    ("application/json", True),
    ("application/octet-stream", False),
    ("application/x-msdownload", False),
    ("application/zip", False),
    ("application/pdf", False),
    ("image/png", False),
    ("video/mp4", False),
])
def test_is_text_content_type(value, expected):
    assert is_text_content_type(value) is expected


def test_binary_content_rejected_without_retry_and_body_not_read(monkeypatch):
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        return httpx.Response(200, content=b"MZ" + b"\x00" * 4096,
                              headers={"content-type": "application/octet-stream"})

    _patch_async_client(monkeypatch, handler)
    result = asyncio.run(HTTPClient(settings=CrawlerSettings()).fetch("https://example.com/setup.exe"))
    assert not result.success
    assert "unsupported content type" in result.error.lower()
    assert result.html is None
    assert calls["n"] == 1


def test_html_page_without_content_type_header_is_accepted(monkeypatch):
    _patch_async_client(monkeypatch, lambda req: httpx.Response(200, content="<html>Příliš žluťoučký kůň</html>".encode("utf-8")))
    result = asyncio.run(HTTPClient(settings=CrawlerSettings()).fetch("https://example.com/"))
    assert result.success
    assert "žluťoučký" in result.html


def test_declared_content_length_over_limit_rejected(monkeypatch):
    def handler(req):
        return httpx.Response(200, content=b"x" * 10, headers={"content-type": "text/html", "content-length": "99999999"})

    _patch_async_client(monkeypatch, handler)
    cfg = CrawlerSettings(max_content_size_mb=0.001)
    result = asyncio.run(HTTPClient(settings=cfg).fetch("https://example.com/"))
    assert not result.success
    assert "too large" in result.error.lower()


def test_not_found_is_not_retried(monkeypatch):
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        return httpx.Response(404, text="nenalezeno")

    _patch_async_client(monkeypatch, handler)
    result = asyncio.run(HTTPClient(settings=CrawlerSettings()).fetch("https://example.com/x"))
    assert not result.success and result.error == "HTTP 404" and result.status_code == 404
    assert calls["n"] == 1
