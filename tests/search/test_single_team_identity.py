"""Běh M589: dotaz na profil týmu (bez home/away) nesmí vracet výsledky bez zmínky o týmu."""
import asyncio

from app.search.engine import SearchEngine
from app.search.models import QuerySpec


class _FakeClient:
    def __init__(self, results):
        self.results = results

    async def search(self, query, language="all", time_range=None):
        return {"results": self.results, "unresponsive_engines": [], "engines": []}


def _run(results, team):
    engine = SearchEngine(client=_FakeClient(results))
    return asyncio.run(engine.search(QuerySpec(query="q"), team=team))


def test_single_team_query_drops_results_without_team_mention():
    results = [
        {"url": "https://sparta.cz/cs/zapas/1", "title": "Sparta Praha – Slovácko", "content": "football match preview league"},
        {"url": "https://example.org/random", "title": "Random football league news", "content": "football match standings league"},
    ]
    urls = [r.url for r in _run(results, "Sparta Praha")]
    assert "https://example.org/random" not in urls


def test_mentions_team_uses_significant_name_parts():
    from app.search.models import SearchResult

    r = SearchResult(title="Sparta v Plzni", url="https://x.cz/a", content="")
    assert SearchEngine._mentions_team(r, "Sparta Praha")
    assert not SearchEngine._mentions_team(SearchResult(title="Praha weather", url="https://x.cz/b", content=""), "Sparta Praha")
