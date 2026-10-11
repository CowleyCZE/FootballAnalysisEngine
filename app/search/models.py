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

@dataclass
class SearchDiagnostics:
    query: str = ""
    raw_count: int = 0
    normalized_count: int = 0
    dedup_count: int = 0
    sport_filtered_count: int = 0
    cutoff_filtered_count: int = 0
    identity_filtered_count: int = 0
    relevance_filtered_count: int = 0
    final_count: int = 0

    @property
    def drop_reasons(self) -> list[str]:
        reasons = []
        if self.raw_count == 0:
            reasons.append(f"Vyhledávač SearXNG nevrátil žádné raw výsledky pro dotaz '{self.query}'.")
        else:
            if self.dedup_count < self.normalized_count:
                reasons.append(f"Deduplikace vyřadila {self.normalized_count - self.dedup_count} duplicitních výsledků.")
            if self.sport_filtered_count < self.dedup_count:
                reasons.append(f"Sportovní filtr vyřadil {self.dedup_count - self.sport_filtered_count} nesportovních výsledků.")
            if self.cutoff_filtered_count < self.sport_filtered_count:
                reasons.append(f"Cutoff filtr vyřadil {self.sport_filtered_count - self.cutoff_filtered_count} výsledků (chybějící nebo novější datum published_at než cutoff).")
            if self.final_count < self.cutoff_filtered_count:
                reasons.append(f"Identitní/relevanční filtr vyřadil {self.cutoff_filtered_count - self.final_count} výsledků (nedostatečná shoda týmu/soutěže).")
        return reasons
