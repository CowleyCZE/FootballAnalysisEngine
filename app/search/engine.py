from __future__ import annotations

from typing import Iterable

from app.search.deduplicator import deduplicate
from app.search.models import QuerySpec, SearchResult
from app.search.normalizer import normalize_searx_result
from app.search.relevance import calculate_relevance
from app.search.searxng_client import SearXNGClient
from app.search.source_registry import SearchSourceRegistry


class SearchEngine:
    """
    Unified search pipeline:

    QuerySpec -> SearXNG -> normalization -> deduplication ->
    source authority/type -> relevance -> ranking.
    """

    def __init__(
        self,
        client: SearXNGClient | None = None,
        source_registry: SearchSourceRegistry | None = None,
    ):
        self.client = client or SearXNGClient()
        self.source_registry = source_registry or SearchSourceRegistry()

    async def search(
        self,
        query: QuerySpec,
        team: str = "",
        topic_terms: list[str] | None = None,
    ) -> list[SearchResult]:
        data = await self.client.search(
            query.query,
            language=query.language,
            time_range=query.time_range,
        )

        normalized = [
            normalize_searx_result(item)
            for item in data.get("results", [])
        ]
        unique = deduplicate(normalized)

        for result in unique:
            info = self.source_registry.get_info(result.url)
            result.source_type = info["source_type"]
            result.relevance = calculate_relevance(
                result,
                team=team,
                topic_terms=topic_terms or [],
                source_priority=query.priority,
                source_authority=info["authority"],
            )

        unique.sort(
            key=lambda result: (
                getattr(result, "relevance", 0),
                result.score,
            ),
            reverse=True,
        )
        return unique

    async def search_many(
        self,
        queries: Iterable[QuerySpec],
        team: str = "",
        topic_terms: list[str] | None = None,
    ) -> list[SearchResult]:
        all_results: list[SearchResult] = []
        for query in queries:
            all_results.extend(
                await self.search(
                    query=query,
                    team=team,
                    topic_terms=topic_terms,
                )
            )
        return deduplicate(all_results)
