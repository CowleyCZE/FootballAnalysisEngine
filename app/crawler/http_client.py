import os
import time
from typing import Optional

import httpx
from app.crawler.config import CrawlerSettings, load_crawler_settings
from app.crawler.models import CrawlResult

# Textové typy, které má smysl parsovat. Chybějící hlavička Content-Type se toleruje (server ji někdy neposílá).
_TEXT_CONTENT_TYPES = frozenset({
    "application/xhtml+xml", "application/xml", "application/rss+xml", "application/atom+xml",
    "application/json", "application/ld+json",
})


def is_text_content_type(content_type: Optional[str]) -> bool:
    """True u textového obsahu nebo bez deklarovaného typu; binární soubory (.exe, zip, obrázky, video, PDF) ne."""
    if not content_type or not content_type.strip():
        return True
    media_type = content_type.split(";", 1)[0].strip().lower()
    return media_type.startswith("text/") or media_type in _TEXT_CONTENT_TYPES


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
        too_large = f"Content too large (> {self.settings.max_content_size_mb:g} MB)"

        for attempt in range(1, self.max_retries + 1):
            try:
                async with httpx.AsyncClient(
                    timeout=self._build_timeout(),
                    follow_redirects=self.settings.follow_redirects,
                    max_redirects=self.settings.max_redirects,
                    headers=headers,
                ) as client:
                    # Stream: hlavičky se vyhodnotí dřív, než se stáhne tělo (binární soubory a obří odpovědi
                    # se nestahují celé – TODO 11.27, např. `.exe` z wemod CDN).
                    async with client.stream("GET", url) as response:
                        content_type = response.headers.get("content-type")

                        def result(success: bool, *, length: int = 0, error: Optional[str] = None,
                                   html: Optional[str] = None) -> CrawlResult:
                            return CrawlResult(
                                url=url,
                                final_url=str(response.url),
                                status_code=response.status_code,
                                content_type=content_type,
                                content_length=length,
                                response_time_ms=int((time.time() - start_time) * 1000),
                                success=success,
                                error=error,
                                html=html,
                            )

                        # Neopravitelné chyby (404/401/403) se neopakují.
                        if response.status_code in [404, 401, 403]:
                            return result(False, error=f"HTTP {response.status_code}")

                        response.raise_for_status()

                        # Netextový obsah se nestahuje ani neopakuje.
                        if not is_text_content_type(content_type):
                            media_type = (content_type or "").split(";", 1)[0].strip().lower()
                            return result(False, error=f"Unsupported content type: {media_type}")

                        # Příliš velký obsah se nezpracovává ani neopakuje (limit z configu).
                        declared = response.headers.get("content-length")
                        if declared and declared.isdigit() and int(declared) > self.max_content_bytes:
                            return result(False, length=int(declared), error=too_large)

                        chunks = []
                        total = 0
                        async for chunk in response.aiter_bytes():
                            total += len(chunk)
                            if total > self.max_content_bytes:
                                return result(False, length=total, error=too_large)
                            chunks.append(chunk)

                        body = b"".join(chunks)
                        try:
                            text = body.decode(response.encoding or "utf-8", errors="replace")
                        except LookupError:
                            text = body.decode("utf-8", errors="replace")
                        return result(True, length=len(body), html=text)

            except httpx.TooManyRedirects as e:
                # Běh M976_c93f: sport.cz ↔ login.seznam.cz autologin je cyklus přesměrování; opakování nemá smysl.
                return CrawlResult(
                    url=url,
                    response_time_ms=int((time.time() - start_time) * 1000),
                    success=False,
                    error=f"Too many redirects: {e}",
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
