from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, List, Dict, Any

class ResearchStatus(str, Enum):
    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    NO_RESULT = "NO_RESULT"
    FAILED = "FAILED"
    CONFLICTED = "CONFLICTED"
    BLOCKED = "BLOCKED"

class ClaimStatus(str, Enum):
    CANDIDATE = "CANDIDATE"
    VALID = "VALID"
    REJECTED = "REJECTED"
    CONFLICTED = "CONFLICTED"
    SUPERSEDED = "SUPERSEDED"

class AbsenceStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    DOUBTFUL = "DOUBTFUL"
    UNAVAILABLE = "UNAVAILABLE"
    SUSPENDED = "SUSPENDED"
    INJURED = "INJURED"
    ILL = "ILL"
    RESTED = "RESTED"
    UNKNOWN = "UNKNOWN"

@dataclass
class ResearchTask:
    task_id: int
    run_id: int
    match_id: int
    domain: str
    task_type: str
    description: str
    required: bool
    priority: int
    data_cutoff_at: datetime
    home_team: str
    away_team: str
    competition: str
    scheduled_at: datetime
    venue: Optional[str] = None
    attempt_number: int = 1

@dataclass
class Evidence:
    source_url: str
    text_fragment: str
    document_id: Optional[int] = None
    published_at: Optional[datetime] = None
    start_offset: Optional[int] = None
    end_offset: Optional[int] = None

@dataclass
class Claim:
    subject: str
    predicate: str
    object_value: Any
    normalized_value: str
    evidence_list: List[Evidence] = field(default_factory=list)
    confidence: float = 1.0
    status: ClaimStatus = ClaimStatus.CANDIDATE
    source_date: Optional[datetime] = None
    conflict_group_id: Optional[str] = None
    claim_id: Optional[int] = None
