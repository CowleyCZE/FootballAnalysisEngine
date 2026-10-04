from __future__ import annotations

import asyncio
import os
from typing import Any, Dict

from app.search.engine import SearchEngine
from app.search.models import QuerySpec
from app.search.searxng_client import SearXNGClient


class SearchWorker:
    """Compatibility worker backed by the unified SearchEngine pipeline."""

    @staticmethod
    def execute(payload: Dict[str, Any]) -> Dict[str, Any]:
        query = str(payload.get("query") or "").strip()
        if not query:
            raise ValueError("SEARCH job requires a non-empty query")

        client = SearXNGClient(
            base_url=os.getenv("SEARXNG_URL", "http://127.0.0.1:8080"),
            timeout=float(os.getenv("SEARXNG_TIMEOUT", "30")),
        )
        engine = SearchEngine(client=client)
        spec = QuerySpec(
            query=query,
            language=str(payload.get("language") or "en"),
            priority=int(payload.get("priority", 50)),
            time_range=payload.get("time_range"),
            reason=str(payload.get("reason") or ""),
        )

        results = asyncio.run(
            engine.search(
                query=spec,
                team=str(payload.get("team") or ""),
                topic_terms=list(payload.get("topic_terms") or []),
            )
        )

        serialized = [
            {
                "title": result.title,
                "url": result.url,
                "snippet": result.content,
                "content": result.content,
                "engine": result.engine,
                "publishedDate": result.published_at,
                "score": result.score,
                "relevance": result.relevance,
                "source_type": result.source_type,
            }
            for result in results
        ]

        return {
            "status": "COMPLETED",
            "query": query,
            "results": serialized,
            "result_count": len(serialized),
            "source": "searxng",
        }
