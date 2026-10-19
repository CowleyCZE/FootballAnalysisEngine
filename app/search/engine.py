from __future__ import annotations

from datetime import datetime, timedelta
from typing import Iterable, Optional

from app.search.deduplicator import deduplicate
from app.search.models import QuerySpec, SearchResult, SearchDiagnostics
from app.search.normalizer import normalize_searx_result
from app.search.relevance import calculate_relevance, calculate_identity_confidence
from app.search.searxng_client import SearXNGClient
from app.search.source_registry import SearchSourceRegistry
from app.search.sport_filter import filter_sports_results


class SearchEngine:
    # SearXNG engines sometimes expose the retrieval minute as
    # ``published_at``. A short ingestion window prevents live searches from
    # rejecting every result while still rejecting clearly newer sources.
    # Some engines expose the calendar day or a delayed crawl timestamp. Keep
    # the evidence, mark it unverified, and let the audit penalize it instead
    # of turning every team profile into NO_RESULT.
    CUTOFF_INGESTION_GRACE_SECONDS = 6 * 60 * 60
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
            unresponsive_engines = []
            engine_errors = []
            engines_used = None
        elif isinstance(data, dict):
            raw_results = data.get("results", [])
            unresponsive_engines, engine_errors = self._unresponsive_details(
                data.get("unresponsive_engines", [])
            )
            engines_used = self._engine_names(data.get("engines", []))
        else:
            raw_results = []
            unresponsive_engines = []
            engine_errors = []
            engines_used = None

        normalized = [normalize_searx_result(item) for item in raw_results]
        unique = deduplicate(normalized)
        sports_filtered = filter_sports_results(unique)

        cutoff_filtered = sports_filtered
        if data_cutoff_at is not None:
            cutoff_filtered = [
                result for result in sports_filtered
                if self._is_at_or_before_cutoff(result, data_cutoff_at)
            ]
        unverified_date_count = sum(1 for result in cutoff_filtered if not getattr(result, "published_at", None))
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

            # A single-team research query is intentionally less strict: an
            # article about Slavia does not need to mention the opponent. H2H
            # queries still use the strict two-team threshold.
            effective_identity_threshold = min_identity_confidence
            if (home_team or away_team) and not (home_team and away_team):
                effective_identity_threshold = min(0.30, min_identity_confidence)
            if (home_team or away_team) and effective_identity_threshold > 0 and confidence < effective_identity_threshold:
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
            unresponsive_engines=unresponsive_engines,
            engine_errors=engine_errors,
            engines_used=engines_used,
            unverified_date_count=unverified_date_count,
        )
        self.last_diagnostics = diag
        return validated_results

    @staticmethod
    def _engine_names(items) -> list[str]:
        """Extract engine names from SearXNG's version-dependent JSON shapes."""
        names = []
        if not isinstance(items, list):
            return names
        for item in items:
            if isinstance(item, dict):
                name = item.get("name") or item.get("engine")
                if name:
                    names.append(str(name))
            elif isinstance(item, (list, tuple)) and item:
                names.append(str(item[0]))
            elif isinstance(item, str):
                names.append(item)
        return names

    @staticmethod
    def _unresponsive_details(items) -> tuple[list[str], list[str]]:
        names, details = [], []
        if not isinstance(items, list):
            return names, details
        for item in items:
            if isinstance(item, dict):
                name = str(item.get("name") or item.get("engine") or "unknown")
                error = item.get("error") or item.get("exception") or item.get("status")
            elif isinstance(item, (list, tuple)) and item:
                name = str(item[0])
                error = item[1] if len(item) > 1 else None
            else:
                name, error = str(item), None
            names.append(name)
            # SearXNG errors are typically short exception/status labels. Keep
            # diagnostics bounded and avoid printing query strings from URLs.
            error_text = str(error).split("?", 1)[0][:180] if error else "bez detailu"
            details.append(f"{name} ({error_text})")
        return names, details

    @staticmethod
    def _is_at_or_before_cutoff(result: SearchResult, cutoff) -> bool:
        published_at = getattr(result, "published_at", None)
        if not published_at:
            # Many official club/league pages do not expose publication
            # metadata. CutoffFilter's documented policy is
            # ``unverified_date``: keep the result, lower its evidential
            # confidence downstream, and let the audit warn instead of
            # silently turning the whole research domain into NO_RESULT.
            return True
        try:
            published = datetime.fromisoformat(str(published_at).replace("Z", "+00:00"))
            if published.tzinfo is None and getattr(cutoff, "tzinfo", None) is not None:
                published = published.replace(tzinfo=cutoff.tzinfo)
            elif getattr(cutoff, "tzinfo", None) is None and published.tzinfo is not None:
                cutoff = cutoff.replace(tzinfo=published.tzinfo)
            if published <= cutoff:
                return True
            retrieved_at = getattr(result, "retrieved_at", None)
            if retrieved_at:
                retrieved = datetime.fromisoformat(str(retrieved_at).replace("Z", "+00:00"))
                if retrieved.tzinfo is None and getattr(cutoff, "tzinfo", None) is not None:
                    retrieved = retrieved.replace(tzinfo=cutoff.tzinfo)
                elif getattr(cutoff, "tzinfo", None) is None and retrieved.tzinfo is not None:
                    retrieved = retrieved.replace(tzinfo=None)
                grace_end = cutoff + timedelta(seconds=SearchEngine.CUTOFF_INGESTION_GRACE_SECONDS)
                if cutoff < published <= grace_end and retrieved <= grace_end:
                    # Do not pass an untrusted publication timestamp to the
                    # audit; it will be handled as UNVERIFIED_DATE.
                    result.published_at = None
                    return True
            return False
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
