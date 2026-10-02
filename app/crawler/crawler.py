import os
import hashlib
import json
import asyncio
from playwright.async_api import async_playwright
from app.crawler.models import CrawlResult, ParsedDocument
from app.crawler.http_client import HTTPClient
from app.crawler.rate_limiter import DomainRateLimiter
from app.parser.html_parser import HTMLParser

class EngineCrawler:
    def __init__(self, user_agent: str = "FootballAnalysisEngine/1.0"):
        self.http_client = HTTPClient(user_agent=user_agent)
        self.rate_limiter = DomainRateLimiter(interval_seconds=2.0)
        self.parser = HTMLParser()

    async def fetch_with_playwright(self, url: str) -> CrawlResult:
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page()
                await page.goto(url, timeout=30000, wait_until="networkidle")
                content = await page.content()
                await browser.close()

                return CrawlResult(
                    url=url,
                    final_url=url,
                    status_code=200,
                    content_length=len(content),
                    success=True,
                    html=content,
                    used_playwright=True
                )
        except Exception as e:
            return CrawlResult(url=url, success=False, error=f"Playwright error: {str(e)}")

    async def crawl_and_parse(self, url: str) -> tuple[CrawlResult, ParsedDocument | None]:
        # 1. Rate limiting
        self.rate_limiter.wait_for_domain(url)

        # 2. HTTP Fetch
        result = await self.http_client.fetch(url)

        # 3. Fallback na Playwright, pokud HTTP vrátilo prázdný/JS obsah
        if result.success and result.html:
            doc = self.parser.parse(result.html, result.final_url or url)
            if doc.word_count < 30:  # Podezření na JS vyrenderovanou stránku
                print(f"[CRAWLER] Nízký počet slov ({doc.word_count}), zkouším Playwright...")
                pw_result = await self.fetch_with_playwright(url)
                if pw_result.success and pw_result.html:
                    result = pw_result
                    doc = self.parser.parse(result.html, result.final_url or url)

            # Uložení RAW HTML a metadat
            self.save_raw(doc.content_hash, result.html, doc)
            return result, doc

        return result, None

    def save_raw(self, content_hash: str, html: str, doc: ParsedDocument):
        os.makedirs("data/raw", exist_ok=True)
        # Uložení RAW HTML
        with open(f"data/raw/{content_hash}.html", "w", encoding="utf-8") as f:
            f.write(html)
        # Uložení metadat
        meta = {
            "url": doc.url,
            "title": doc.title,
            "retrieved_at": doc.retrieved_at,
            "published_at": doc.published_at,
            "word_count": doc.word_count,
            "quality_score": doc.quality_score
        }
        with open(f"data/raw/{content_hash}.json", "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)