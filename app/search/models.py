from dataclasses import dataclass
from typing import Optional

@dataclass
class SearchResult:
    title: str
    url: str
    content: str
    engine: Optional[str] = None
    category: Optional[str] = None
    published_at: Optional[str] = None
    score: float = 0.0
    relevance: int = 0
    source_type: str = "search"
    retrieved_at: Optional[str] = None

@dataclass
class QuerySpec:
    query: str
    language: str = "all"
    priority: int = 50
    time_range: Optional[str] = None
    reason: str = ""
