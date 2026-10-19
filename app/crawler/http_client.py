import time
import httpx
from app.crawler.models import CrawlResult

class HTTPClient:
    def __init__(self, user_agent: str, timeout: int = 20, max_retries: int = 3):
        self.user_agent = user_agent
        self.timeout = timeout
        self.max_retries = max_retries

    async def fetch(self, url: str) -> CrawlResult:
        headers = {"User-Agent": self.user_agent}
        start_time = time.time()

        for attempt in range(1, self.max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True, headers=headers) as client:
                    response = await client.get(url)
                    response_time = int((time.time() - start_time) * 1000)

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