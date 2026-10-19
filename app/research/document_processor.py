from typing import Dict, Any, Optional
from datetime import datetime, timezone


class DocumentProcessor:
    def process(self, raw_doc: Dict[str, Any]) -> Dict[str, Any]:
        text = str(raw_doc.get("text") or raw_doc.get("content") or "").strip()
        quality = "VALID"

        if not text:
            quality = "EMPTY"
        elif len(text) < 50:
            quality = "TOO_SHORT"
        elif "paywall" in text.lower() or "subscribe to read" in text.lower():
            quality = "PAYWALLED"

        pub_at = raw_doc.get("published_at")
        published_dt: Optional[datetime] = None
        if isinstance(pub_at, datetime):
            published_dt = pub_at
        elif isinstance(pub_at, str) and pub_at:
            try:
                published_dt = datetime.fromisoformat(pub_at.replace("Z", "+00:00"))
            except ValueError:
                published_dt = None

        retrieved_at = raw_doc.get("retrieved_at") or datetime.now(timezone.utc).isoformat()

        return {
            "title": str(raw_doc.get("title") or ""),
            "text": text,
            "url": str(raw_doc.get("url") or ""),
            "canonical_url": str(raw_doc.get("canonical_url") or raw_doc.get("url") or ""),
            "published_at": published_dt,
            "retrieved_at": retrieved_at,
            "quality": quality,
            "language": str(raw_doc.get("language") or "en"),
            "word_count": len(text.split()),
            "content_hash": str(raw_doc.get("content_hash") or ""),
            "quality_score": float(raw_doc.get("quality_score", 1.0) or 1.0),
            "document_id": raw_doc.get("document_id"),
        }
