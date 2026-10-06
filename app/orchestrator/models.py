from datetime import datetime
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


class AnalysisRequest(BaseModel):
    home_team: str
    away_team: str
    competition: str
    scheduled_at: datetime
    timezone: str = "Europe/Prague"
    requested_by: str = "user"
    priority: int = 50


class MatchIdentity(BaseModel):
    match_id: int
    home_team_id: Optional[int] = None
    away_team_id: Optional[int] = None
    competition_id: Optional[int] = None
    home_team: str = ""
    away_team: str = ""
    competition: str = ""
    scheduled_at: datetime
    data_cutoff_at: datetime
    venue: Optional[str] = None


class TaskRequirement(BaseModel):
    task_uuid: str
    domain: str
    task_type: str
    description: str
    priority: int = 50
    required: bool = False
    capabilities_required: List[str] = Field(default_factory=list)


class ResearchManifest(BaseModel):
    run_uuid: str
    match_id: int
    cutoff: str
    policy_version: str
    plan_version: str
    required_domains: List[str]
    optional_domains: List[str]
    tasks_count: int


class ResearchReadiness(BaseModel):
    ready: bool
    required_complete: bool
    coverage_score: float
    critical_conflicts: int
    warnings: List[str] = Field(default_factory=list)
    blocking_reasons: List[str] = Field(default_factory=list)
