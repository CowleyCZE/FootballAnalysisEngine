from typing import Dict, Any

class CrawlerWorker:
    @staticmethod
    def execute(payload: Dict[str, Any]) -> Dict[str, Any]:
        url = payload.get("url", "https://example.com")
        return {
            "status": "crawled",
            "url": url,
            "raw_text": "Sestava: Hráč X nastoupil. Hráč Y chybí pro zranění."
        }
