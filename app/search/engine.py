from __future__ import annotations

from typing import Iterable, Optional

from app.search.deduplicator import deduplicate
from app.search.models import QuerySpec, SearchResult, SearchDiagnostics
from app.search.normalizer import normalize_searx_result
from app.search.relevance import calculate_relevance, calculate_identity_confidence
from app.search.searxng_client import SearXNGClient
from app.search.source_registry import SearchSourceRegistry
from app.search.sport_filter import filter_sports_results


class SearchEngine:
    """
    Unified search pipeline.

    Flow:
        QuerySpec
          -> SearXNG
          -> normalization
          -> deduplication
          -> source authority
          -> identity confidence check
          -> relevance
          -> ranking
    """

    def __init__(
        self,
        client: SearXNGClient | None = None,
        source_registry: SearchSourceRegistry | None = None,
    ):
        self.client = client or SearXNGClient()
        self.source_registry = source_registry or SearchSourceRegistry()
        self.last_diagnostics: Optional[SearchDiagnostics] = None

    async def search(
        self,
        query: QuerySpec,
        team: str = "",
        topic_terms: list[str] | None = None,
        data_cutoff_at=None,
        home_team: Optional[str] = None,
        away_team: Optional[str] = None,
        competition: Optional[str] = None,
        min_identity_confidence: float = 0.6,
    ) -> list[SearchResult]:
        data = await self.client.search(
            query.query,
            language=query.language,
            time_range=query.time_range,
        )

        if isinstance(data, list):
            raw_results = data
        elif isinstance(data, dict):
            raw_results = data.get("results", [])
        else:
            raw_results = []

        normalized = [normalize_searx_result(item) for item in raw_results]
        unique = deduplicate(normalized)
        sports_filtered = filter_sports_results(unique)

        cutoff_filtered = sports_filtered
        if data_cutoff_at is not None:
            cutoff_filtered = [
                result for result in sports_filtered
                if self._is_at_or_before_cutoff(result, data_cutoff_at)
            ]
        terms = topic_terms or []

        validated_results = []
        for result in cutoff_filtered:
            info = self.source_registry.get_info(result.url)
            result.source_type = info["source_type"]

            confidence = calculate_identity_confidence(
                result,
                home_team=home_team or team,
                away_team=away_team,
                competition=competition,
                scheduled_at=data_cutoff_at,
            )

            # Strict threshold check if teams were provided
            if (home_team or away_team) and min_identity_confidence > 0 and confidence < min_identity_confidence:
                continue

            result.relevance = calculate_relevance(
                result,
                team=team,
                topic_terms=terms,
                source_priority=query.priority,
                source_authority=info["authority"],
                data_cutoff_at=data_cutoff_at,
                home_team=home_team,
                away_team=away_team,
                competition=competition,
            )
            validated_results.append(result)

        validated_results.sort(
            key=lambda result: (
                getattr(result, "relevance", 0),
                result.score,
            ),
            reverse=True,
        )

        diag = SearchDiagnostics(
            query=query.query,
            raw_count=len(raw_results),
            normalized_count=len(normalized),
            dedup_count=len(unique),
            sport_filtered_count=len(sports_filtered),
            cutoff_filtered_count=len(cutoff_filtered),
            identity_filtered_count=len(validated_results),
            relevance_filtered_count=len(validated_results),
            final_count=len(validated_results),
        )
        self.last_diagnostics = diag
        return validated_results

    @staticmethod
    def _is_at_or_before_cutoff(result: SearchResult, cutoff) -> bool:
        published_at = getattr(result, "published_at", None)
        if not published_at:
            return False
        try:
            from datetime import datetime
            published = datetime.fromisoformat(str(published_at).replace("Z", "+00:00"))
            if published.tzinfo is None and getattr(cutoff, "tzinfo", None) is not None:
                published = published.replace(tzinfo=cutoff.tzinfo)
            elif getattr(cutoff, "tzinfo", None) is None and published.tzinfo is not None:
                cutoff = cutoff.replace(tzinfo=published.tzinfo)
            return published <= cutoff
        except (TypeError, ValueError):
            return False

    async def search_many(
        self,
        queries: Iterable[QuerySpec],
        team: str = "",
        topic_terms: list[str] | None = None,
        data_cutoff_at=None,
        home_team: Optional[str] = None,
        away_team: Optional[str] = None,
        competition: Optional[str] = None,
    ) -> list[SearchResult]:
        all_results: list[SearchResult] = []
        for query in queries:
            all_results.extend(
                await self.search(
                    query=query,
                    team=team,
                    topic_terms=topic_terms,
                    data_cutoff_at=data_cutoff_at,
                    home_team=home_team,
                    away_team=away_team,
                    competition=competition,
                )
            )
        return deduplicate(all_results)
