from dataclasses import dataclass
from typing import Optional, Dict, Any

@dataclass
class CrawlResult:
    url: str
    final_url: Optional[str] = None
    status_code: Optional[int] = None
    content_type: Optional[str] = None
    content_length: int = 0
    response_time_ms: int = 0
    success: bool = False
    error: Optional[str] = None
    html: Optional[str] = None
    used_playwright: bool = False
    from_cache: bool = False

@dataclass
class ParsedDocument:
    url: str
    canonical_url: Optional[str]
    title: Optional[str]
    description: Optional[str]
    author: Optional[str]
    published_at: Optional[str]
    retrieved_at: str
    language: str
    text: str
    word_count: int
    content_hash: str
    quality_score: float