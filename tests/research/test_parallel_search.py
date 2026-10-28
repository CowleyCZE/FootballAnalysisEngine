"""Souběžné vyhledávací dotazy research úkolu (zrychlení researchu, bod 1)."""
import asyncio
import threading
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.research.engine import ResearchEngine
from app.search.engine import SearchEngine
from app.search.searxng_client import SearXNGClient


class _TrackingAdapter:
    """Fake adaptér: eviduje maximální počet souběžných volání a pořadí dotazů."""

    def __init__(self, delay=0.1, fail_on=None):
        self.delay = delay
        self.fail_on = fail_on
        self.active = 0
        self.max_active = 0
        self._lock = threading.Lock()
        self.last_diagnostics = None

    def search(self, query, **kwargs):
        with self._lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            time.sleep(self.delay)
            if self.fail_on and query == self.fail_on:
                raise RuntimeError(f"boom {query}")
            return [f"result:{query}"]
        finally:
            with self._lock:
                self.active -= 1


def _task():
    return SimpleNamespace(
        domain="TEAM_PROFILE_HOME", home_team="Sparta Praha", away_team="Slovácko",
        competition="Chance Liga", priority=50, data_cutoff_at=None,
    )


def _queries(n=4):
    return [{"query": f"q{i}", "type": "discovery", "hash": f"h{i}"} for i in range(n)]


def _engine(adapter):
    return ResearchEngine(search_adapter=adapter, repository=MagicMock())


def test_queries_run_concurrently_and_keep_order(monkeypatch):
    monkeypatch.setenv("FAE_SEARCH_WORKERS", "3")
    adapter = _TrackingAdapter()
    outcomes = _engine(adapter)._search_parallel(_task(), _queries(4))

    assert adapter.max_active >= 2
    assert [o[0] for o in outcomes] == [["result:q0"], ["result:q1"], ["result:q2"], ["result:q3"]]
    assert all(o[1] is None for o in outcomes)


def test_single_worker_is_sequential(monkeypatch):
    monkeypatch.setenv("FAE_SEARCH_WORKERS", "1")
    adapter = _TrackingAdapter(delay=0.02)
    outcomes = _engine(adapter)._search_parallel(_task(), _queries(3))

    assert adapter.max_active == 1
    assert len(outcomes) == 3


def test_invalid_worker_setting_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("FAE_SEARCH_WORKERS", "abc")
    adapter = _TrackingAdapter(delay=0.02)
    outcomes = _engine(adapter)._search_parallel(_task(), _queries(3))
    assert len(outcomes) == 3


def test_search_error_is_returned_not_raised_and_order_preserved(monkeypatch):
    monkeypatch.setenv("FAE_SEARCH_WORKERS", "3")
    adapter = _TrackingAdapter(delay=0.02, fail_on="q1")
    outcomes = _engine(adapter)._search_parallel(_task(), _queries(3))

    assert outcomes[0][1] is None and outcomes[2][1] is None
    assert isinstance(outcomes[1][1], RuntimeError)
    assert outcomes[1][0] == []


def test_search_diagnostics_are_thread_local():
    engine = SearchEngine(client=MagicMock())
    seen = {}

    def worker(name):
        engine.last_diagnostics = name
        time.sleep(0.05)
        seen[name] = engine.last_diagnostics

    threads = [threading.Thread(target=worker, args=(f"d{i}",)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert seen == {f"d{i}": f"d{i}" for i in range(4)}
    assert engine.last_diagnostics is None  # hlavní vlákno nic nenastavilo


class _FakeResponse:
    status_code = 200

    def raise_for_status(self):
        pass

    def json(self):
        return {"results": []}


def _run_client_search(monkeypatch, tmp_path, hold):
    """Vrátí True, pokud byl host-zámek v okamžiku HTTP požadavku volný."""
    import fcntl

    lock_path = tmp_path / "searx.lock"
    monkeypatch.setenv("SEARXNG_THROTTLE_FILE", str(lock_path))
    monkeypatch.setenv("SEARXNG_MIN_INTERVAL_SECONDS", "0.01")
    monkeypatch.setenv("SEARXNG_HOLD_LOCK", "1" if hold else "0")
    free = {}

    class _FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, *args, **kwargs):
            with open(lock_path, "a+") as probe:
                try:
                    fcntl.flock(probe.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    fcntl.flock(probe.fileno(), fcntl.LOCK_UN)
                    free["value"] = True
                except OSError:
                    free["value"] = False
            return _FakeResponse()

    monkeypatch.setattr("app.search.searxng_client.httpx.AsyncClient", _FakeAsyncClient)
    asyncio.run(SearXNGClient(base_url="http://x").search("q"))
    return free["value"]


def test_searxng_lock_released_before_request_by_default(monkeypatch, tmp_path):
    assert _run_client_search(monkeypatch, tmp_path, hold=False) is True


def test_searxng_lock_held_during_request_when_requested(monkeypatch, tmp_path):
    assert _run_client_search(monkeypatch, tmp_path, hold=True) is False


class _SlowCrawler:
    def __init__(self, delay=0.1):
        self.delay = delay
        self.active = 0
        self.max_active = 0
        self._lock = threading.Lock()

    def crawl(self, url):
        with self._lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            time.sleep(self.delay)
            if url.endswith("bad"):
                raise RuntimeError("crawl boom")
            return {"status": "success", "url": url}
        finally:
            with self._lock:
                self.active -= 1


def test_crawl_parallel_keeps_order_and_isolates_errors(monkeypatch):
    monkeypatch.setenv("FAE_CRAWL_WORKERS", "4")
    crawler = _SlowCrawler()
    engine = ResearchEngine(search_adapter=_TrackingAdapter(), crawler=crawler, repository=MagicMock())
    urls = ["https://a.cz/1", "https://b.cz/bad", "https://c.cz/3", "https://d.cz/4"]

    results = engine._crawl_parallel(urls)

    assert crawler.max_active >= 2
    assert [r["url"] for r in results] == urls
    assert [r["status"] for r in results] == ["success", "error", "success", "success"]


def test_crawl_single_worker_is_sequential(monkeypatch):
    monkeypatch.setenv("FAE_CRAWL_WORKERS", "1")
    crawler = _SlowCrawler(delay=0.02)
    engine = ResearchEngine(search_adapter=_TrackingAdapter(), crawler=crawler, repository=MagicMock())

    engine._crawl_parallel(["https://a.cz/1", "https://b.cz/2", "https://c.cz/3"])

    assert crawler.max_active == 1
