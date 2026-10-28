"""Playwright se spouští jen u krátkých stránek, které vypadají jako JS aplikace."""
import asyncio

import pytest

from app.crawler.crawler import EngineCrawler, looks_js_rendered
from app.crawler.models import CrawlResult

SPA_HTML = '<html><head><title>App</title></head><body><div id="root"></div><script src="/app.js"></script></body></html>'
EMPTY_HTML = "<html><head><title>Nenalezeno</title></head><body><p>Stránka neexistuje.</p></body></html>"
LONG_TEXT = " ".join(f"slovo{i}" for i in range(120))
FULL_HTML = f"<html><head><title>Plná stránka</title></head><body><article><p>{LONG_TEXT}</p></article></body></html>"


@pytest.mark.parametrize("html,expected", [
    (SPA_HTML, True),
    ('<html><body><div id="__next"></div></body></html>', True),
    ("<html><body><noscript>Please enable JavaScript to continue</noscript></body></html>", True),
    ("<html><body><script></script><script></script><script></script></body></html>", True),
    (EMPTY_HTML, False),
    ("", False),
    (None, False),
])
def test_looks_js_rendered(html, expected):
    assert looks_js_rendered(html) is expected


def _crawler(monkeypatch, tmp_path, fetched_html, pw_html=FULL_HTML):
    monkeypatch.chdir(tmp_path)  # save_raw zapisuje do data/raw
    crawler = EngineCrawler()
    calls = {"playwright": 0}

    async def fake_fetch(url):
        return CrawlResult(url=url, final_url=url, status_code=200, success=True, html=fetched_html)

    async def fake_playwright(url):
        calls["playwright"] += 1
        return CrawlResult(url=url, final_url=url, status_code=200, success=True, html=pw_html, used_playwright=True)

    monkeypatch.setattr(crawler.http_client, "fetch", fake_fetch)
    monkeypatch.setattr(crawler, "fetch_with_playwright", fake_playwright)
    monkeypatch.setattr(crawler.rate_limiter, "wait_for_domain", lambda url: None)
    return crawler, calls


def test_playwright_skipped_for_short_non_js_page(monkeypatch, tmp_path):
    crawler, calls = _crawler(monkeypatch, tmp_path, EMPTY_HTML)
    result, doc = asyncio.run(crawler.crawl_and_parse("https://example.cz/404"))
    assert calls["playwright"] == 0
    assert doc is not None and doc.word_count < 30


def test_playwright_used_for_short_js_page_and_result_replaced(monkeypatch, tmp_path):
    crawler, calls = _crawler(monkeypatch, tmp_path, SPA_HTML)
    result, doc = asyncio.run(crawler.crawl_and_parse("https://example.cz/spa"))
    assert calls["playwright"] == 1
    assert result.used_playwright is True
    assert doc.word_count >= 100


def test_playwright_not_used_for_full_page(monkeypatch, tmp_path):
    crawler, calls = _crawler(monkeypatch, tmp_path, FULL_HTML)
    result, doc = asyncio.run(crawler.crawl_and_parse("https://example.cz/clanek"))
    assert calls["playwright"] == 0
    assert doc.word_count >= 100
