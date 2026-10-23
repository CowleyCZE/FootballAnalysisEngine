import os
import time
from typing import Optional

import httpx
from app.crawler.config import CrawlerSettings, load_crawler_settings
from app.crawler.models import CrawlResult

class HTTPClient:
    """HTTP klient crawleru. Nezadané parametry se berou z `config/crawler.yaml` (TODO 5.3)."""

    def __init__(
        self,
        user_agent: Optional[str] = None,
        timeout: Optional[float] = None,
        max_retries: Optional[int] = None,
        settings: Optional[CrawlerSettings] = None,
    ):
        self.settings = settings or load_crawler_settings()
        self.user_agent = user_agent or self.settings.user_agent
        self.timeout = timeout if timeout is not None else self.settings.timeout_seconds
        self.max_retries = max_retries if max_retries is not None else self.settings.max_retries
        self.max_content_bytes = int(self.settings.max_content_size_mb * 1024 * 1024)

    def _build_timeout(self) -> httpx.Timeout:
        connect = min(self.settings.connect_timeout_seconds, float(self.timeout))
        return httpx.Timeout(float(self.timeout), connect=connect)

    async def fetch(self, url: str) -> CrawlResult:
        user_agent = self.user_agent
        contact = os.getenv("FAE_CONTACT", "").strip()  # Wikimedia a další vyžadují v UA kontakt (robot policy)
        if contact and contact not in user_agent:
            user_agent = f"{user_agent} ({contact})"
        headers = {
            "User-Agent": user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "cs,en;q=0.8",
        }
        start_time = time.time()

        for attempt in range(1, self.max_retries + 1):
            try:
                async with httpx.AsyncClient(
                    timeout=self._build_timeout(),
                    follow_redirects=self.settings.follow_redirects,
                    max_redirects=self.settings.max_redirects,
                    headers=headers,
                ) as client:
                    response = await client.get(url)
                    response_time = int((time.time() - start_time) * 1000)

                    # Příliš velký obsah se nezpracovává ani neopakuje (limit z configu).
                    if len(response.content) > self.max_content_bytes:
                        return CrawlResult(
                            url=url,
                            final_url=str(response.url),
                            status_code=response.status_code,
                            content_type=response.headers.get("content-type"),
                            content_length=len(response.content),
                            response_time_ms=response_time,
                            success=False,
                            error=f"Content too large (> {self.settings.max_content_size_mb:g} MB)"
                        )

                    # Kontrola status kódů (neopravitelné chyby jako 404/403 neopakovat)
                    if response.status_code in [404, 401, 403]:
                        return CrawlResult(
                            url=url,
                            final_url=str(response.url),
                            status_code=response.status_code,
                            content_type=response.headers.get("content-type"),
                            content_length=len(response.content),
                            response_time_ms=response_time,
                            success=False,
                            error=f"HTTP {response.status_code}"
                        )

                    response.raise_for_status()
                    return CrawlResult(
                        url=url,
                        final_url=str(response.url),
                        status_code=response.status_code,
                        content_type=response.headers.get("content-type"),
                        content_length=len(response.content),
                        response_time_ms=response_time,
                        success=True,
                        html=response.text
                    )

            except Exception as e:
                if attempt == self.max_retries:
                    response_time = int((time.time() - start_time) * 1000)
                    return CrawlResult(
                        url=url,
                        response_time_ms=response_time,
                        success=False,
                        error=str(e)
                    )
                # Exponenciální backoff
                time.sleep(2 ** (attempt - 1))