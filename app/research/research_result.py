from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from app.research.models import ResearchStatus, Claim

@dataclass
class ResearchMetrics:
    queries_count: int = 0
    search_results_count: int = 0
    sources_selected: int = 0
    sources_crawled: int = 0
    documents_parsed: int = 0
    claims_count: int = 0
    valid_claims_count: int = 0
    conflicts_count: int = 0
    duration_ms: int = 0

@dataclass
class ResearchResult:
    task_id: int
    execution_id: str
    status: ResearchStatus
    claims: List[Claim] = field(default_factory=list)
    sources_count: int = 0
    documents_count: int = 0
    evidence_count: int = 0
    conflicts_count: int = 0
    warnings: List[str] = field(default_factory=list)
    metrics: ResearchMetrics = field(default_factory=ResearchMetrics)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "execution_id": self.execution_id,
            "status": self.status.value,
            "claims": len(self.claims),
            "valid_claims": sum(1 for c in self.claims if c.status == "VALID"),
            "sources": self.sources_count,
            "documents": self.documents_count,
            "evidence": self.evidence_count,
            "conflicts": self.conflicts_count,
            "warnings": self.warnings,
            "metrics": self.metrics.__dict__
        }
