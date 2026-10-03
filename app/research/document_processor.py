from typing import Dict, Any, Optional
from datetime import datetime

class DocumentProcessor:
    def process(self, raw_doc: Dict[str, Any]) -> Dict[str, Any]:
        text = raw_doc.get("text", "").strip()
        quality = "VALID"
        
        if not text:
            quality = "EMPTY"
        elif len(text) < 100:
            quality = "TOO_SHORT"
        elif "paywall" in text.lower() or "subscribe to read" in text.lower():
            quality = "PAYWALLED"

        pub_at = raw_doc.get("published_at")
        published_dt = None
        if isinstance(pub_at, str) and pub_at:
            try:
                published_dt = datetime.fromisoformat(pub_at.replace("Z", "+00:00"))
            except ValueError:
                published_dt = None

        return {
            "title": raw_doc.get("title", ""),
            "text": text,
            "url": raw_doc.get("url", ""),
            "published_at": published_dt,
            "quality": quality,
            "language": raw_doc.get("language", "en")
        }
