from datetime import datetime, timezone
from app.search.models import SearchResult

def normalize_searx_result(item: dict) -> SearchResult:
    return SearchResult(
        title=str(item.get("title", "")).strip(),
        url=str(item.get("url", "")).strip(),
        content=str(item.get("content", "")).strip(),
        engine=item.get("engine"),
        category=item.get("category"),
        published_at=item.get("publishedDate") or item.get("published_at"),
        score=float(item.get("score", 0.0) or 0.0),
        source_type="search",
        retrieved_at=datetime.now(timezone.utc).isoformat(),
    )