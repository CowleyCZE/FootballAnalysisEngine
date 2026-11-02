"""Běh M976_c93f: cyklus přesměrování (sport.cz ↔ login.seznam.cz) se nesmí opakovat při každém pokusu."""
import asyncio

import httpx

from app.crawler import http_client as http_client_module
from app.crawler.config import CrawlerSettings
from app.crawler.http_client import HTTPClient


def test_redirect_loop_fails_without_retry(monkeypatch):
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        return httpx.Response(302, headers={"location": str(req.url)})

    real = httpx.AsyncClient

    def factory(*args, **kwargs):
        return real(*args, transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(http_client_module.httpx, "AsyncClient", factory)
    settings = CrawlerSettings()
    result = asyncio.run(HTTPClient(settings=settings, max_retries=3).fetch("https://www.sport.cz/clanek/x"))
    assert not result.success
    assert "redirect" in result.error.lower()
    assert calls["n"] <= settings.max_redirects + 1  # jediný pokus, žádné opakování
