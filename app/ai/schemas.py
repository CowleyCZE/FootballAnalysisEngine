from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field

class EvidenceItem(BaseModel):
    evidence_id: Optional[int] = None
    source: str
    url: Optional[str] = None
    published_at: Optional[str] = None
    excerpt: str

class ClaimItem(BaseModel):
    claim_id: int
    subject: str
    predicate: str
    object_value: str = Field(alias="object", default="")
    confidence: float
    status: str
    evidence: List[EvidenceItem] = Field(default_factory=list)

class KeyFactor(BaseModel):
    factor: str
    importance: float = Field(ge=0.0, le=1.0)
    evidence_ids: List[int] = Field(default_factory=list)

class DataQuality(BaseModel):
    score: float = Field(ge=0.0, le=1.0)
    source_count: int = 0
    independent_sources: int = 0
    official_sources: int = 0
    conflicts: int = 0
    freshness_score: float = 1.0
    missing_data: List[str] = Field(default_factory=list)

class TeamAnalysis(BaseModel):
    strengths: List[str] = Field(default_factory=list)
    weaknesses: List[str] = Field(default_factory=list)
    tactical_notes: List[str] = Field(default_factory=list)

class AnalysisResult(BaseModel):
    match_id: int
    status: str = "complete"  # "complete" nebo "insufficient_data"
    data_quality: DataQuality
    home_team_analysis: Optional[TeamAnalysis] = None
    away_team_analysis: Optional[TeamAnalysis] = None
    key_factors: List[KeyFactor] = Field(default_factory=list)
    uncertainties: List[str] = Field(default_factory=list)
    conflicts_noted: List[str] = Field(default_factory=list)
    conclusion: str
