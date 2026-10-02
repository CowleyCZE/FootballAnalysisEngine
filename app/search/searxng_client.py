from __future__ import annotations
import httpx

class SearXNGClient:
    def __init__(self, base_url: str = "http://127.0.0.1:8080", timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def search(self, query: str, language: str = "all", page: int = 1, time_range: str | None = None) -> dict:
        params = {
            "q": query,
            "format": "json",
            "language": language,
            "pageno": page,
        }
        if time_range:
            params["time_range"] = time_range

        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
            response = await client.get(f"{self.base_url}/search", params=params)
            response.raise_for_status()
            return response.json()