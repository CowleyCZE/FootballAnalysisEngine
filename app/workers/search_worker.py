import os
from typing import Any, Dict

import httpx


class SearchWorker:
    """SearXNG worker. No fabricated search results are returned."""

    @staticmethod
    def execute(payload: Dict[str, Any]) -> Dict[str, Any]:
        query = str(payload.get("query") or "").strip()
        if not query:
            raise ValueError("SEARCH job requires a non-empty query")

        base_url = os.getenv("SEARXNG_URL", "http://127.0.0.1:8080").rstrip("/")
        timeout = float(os.getenv("SEARXNG_TIMEOUT", "30"))
        url = f"{base_url}/search"
        params = {"q": query, "format": "json", "language": "en"}

        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            response = client.get(url, params=params)
            response.raise_for_status()
            data = response.json()

        results = []
        for item in data.get("results", []):
            result_url = item.get("url")
            if not result_url:
                continue
            results.append({
                "title": item.get("title", ""),
                "url": result_url,
                "snippet": item.get("content", ""),
                "engine": item.get("engine"),
                "publishedDate": item.get("publishedDate"),
            })

        return {
            "status": "COMPLETED",
            "query": query,
            "results": results,
            "result_count": len(results),
            "source": "searxng",
        }
