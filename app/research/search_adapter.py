from __future__ import annotations

import asyncio
from typing import Any, Iterable, List

from app.search.engine import SearchEngine
from app.search.models import QuerySpec, SearchResult
from app.research.topic_terms import get_topic_terms


class SearchAdapter:
    """
    Synchronous compatibility boundary between ResearchEngine and SearchEngine.

    ResearchEngine is intentionally synchronous. SearchEngine is asynchronous
    because its network client uses httpx.AsyncClient. This adapter owns the
    event-loop bridge so ResearchEngine never needs to know about async details.
    """

    def __init__(self, search_engine: SearchEngine | None = None):
        self.search_engine = search_engine or SearchEngine()

    def search(
        self,
        query: str | QuerySpec,
        *,
        team: str = "",
        domain: str = "",
        priority: int = 50,
        language: str = "all",
        time_range: str | None = None,
        reason: str = "",
    ) -> List[SearchResult]:
        spec = self._build_query_spec(
            query,
            priority=priority,
            language=language,
            time_range=time_range,
            reason=reason,
        )
        terms = get_topic_terms(domain)
        return self._run(
            self.search_engine.search(
                query=spec,
                team=team,
                topic_terms=terms,
            )
        )

    def search_many(
        self,
        queries: Iterable[str | QuerySpec],
        *,
        team: str = "",
        domain: str = "",
        priority: int = 50,
        language: str = "all",
        time_range: str | None = None,
    ) -> List[SearchResult]:
        specs = [
            self._build_query_spec(
                query,
                priority=priority,
                language=language,
                time_range=time_range,
            )
            for query in queries
        ]
        terms = get_topic_terms(domain)
        return self._run(
            self.search_engine.search_many(
                queries=specs,
                team=team,
                topic_terms=terms,
            )
        )

    @staticmethod
    def _build_query_spec(
        query: str | QuerySpec,
        *,
        priority: int,
        language: str,
        time_range: str | None,
        reason: str = "",
    ) -> QuerySpec:
        if isinstance(query, QuerySpec):
            return query

        return QuerySpec(
            query=str(query),
            language=language,
            priority=priority,
            time_range=time_range,
            reason=reason,
        )

    @staticmethod
    def _run(awaitable: Any):
        """
        Execute a coroutine from synchronous code.

        A fresh loop is used when the calling thread has no active event loop.
        When an event loop is already running in this thread, execution is
        delegated to a worker thread with its own loop.
        """
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(awaitable)

        import threading

        result: list[Any] = []
        error: list[BaseException] = []

        def runner() -> None:
            try:
                result.append(asyncio.run(awaitable))
            except BaseException as exc:  # pragma: no cover - defensive bridge
                error.append(exc)

        thread = threading.Thread(target=runner, daemon=True)
        thread.start()
        thread.join()

        if error:
            raise error[0]

        return result[0] if result else []
