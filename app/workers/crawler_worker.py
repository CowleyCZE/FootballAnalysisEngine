import asyncio
from typing import Any, Dict

from app.crawler.crawler import EngineCrawler


class CrawlerWorker:
    @staticmethod
    def execute(payload: Dict[str, Any]) -> Dict[str, Any]:
        url = str(payload.get("url") or "").strip()
        if not url:
            raise ValueError("CRAWL job requires a URL")

        crawler = EngineCrawler()
        result, document = asyncio.run(crawler.crawl_and_parse(url))
        if not result.success:
            raise RuntimeError(result.error or f"Crawler failed for {url}")

        return {
            "status": "COMPLETED",
            "url": result.url,
            "final_url": result.final_url,
            "status_code": result.status_code,
            "content_length": result.content_length,
            "used_playwright": result.used_playwright,
            "content_hash": getattr(document, "content_hash", None) if document else None,
            "title": getattr(document, "title", None) if document else None,
            "word_count": getattr(document, "word_count", 0) if document else 0,
            "quality_score": getattr(document, "quality_score", None) if document else None,
        }
