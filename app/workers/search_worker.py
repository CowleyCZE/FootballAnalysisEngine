from __future__ import annotations

import asyncio
import os
from typing import Any, Dict, List

import httpx


class SearchWorker:
    """Compatibility worker backed by the unified SearchEngine pipeline with Note 9 lightweight proxy support."""

    @staticmethod
    def execute(payload: Dict[str, Any]) -> Dict[str, Any]:
        query = str(payload.get("query") or "").strip()
        if not query:
            raise ValueError("SEARCH job requires a non-empty query")

        search_api_url = os.getenv("SEARCH_API_URL") or payload.get("search_api_url")
        use_proxy = bool(payload.get("use_proxy") or search_api_url or os.getenv("USE_SEARCH_PROXY"))

        if use_proxy:
            proxy_url = search_api_url or "http://127.0.0.1:8000/api/internal/search"
            proxy_payload = {
                "query": query,
                "language": str(payload.get("language") or "en"),
                "priority": int(payload.get("priority", 50)),
                "time_range": payload.get("time_range"),
                "reason": str(payload.get("reason") or ""),
                "team": str(payload.get("team") or ""),
                "topic_terms": list(payload.get("topic_terms") or []),
                "data_cutoff_at": payload.get("data_cutoff_at") or payload.get("cutoff"),
            }
            headers = {}
            token = os.getenv("WORKER_API_TOKEN") or os.getenv("API_SECRET_TOKEN")
            if token:
                headers["X-Worker-Token"] = token
                headers["Authorization"] = f"Bearer {token}"

            with httpx.Client(timeout=30.0) as client:
                resp = client.post(proxy_url, json=proxy_payload, headers=headers)
                resp.raise_for_status()
                return resp.json()

        from app.search.engine import SearchEngine
        from app.search.models import QuerySpec
        from app.search.searxng_client import SearXNGClient

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
                "published_at": result.published_at,
                "score": result.score,
                "relevance": result.relevance,
                "source_type": result.source_type,
                "retrieved_at": result.retrieved_at,
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
