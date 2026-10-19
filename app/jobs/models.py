from dataclasses import dataclass, field
from enum import IntEnum
from typing import Dict, Any, Optional

class JobStatus:
    PENDING = "PENDING"
    CLAIMED = "CLAIMED"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    RETRY = "RETRY"
    CANCELLED = "CANCELLED"
    BLOCKED = "BLOCKED"


class JobPriority(IntEnum):
    BACKGROUND = 10
    LOW = 30
    MEDIUM = 50
    NORMAL = 50
    HIGH = 80
    CRITICAL = 100


@dataclass
class JobModel:
    job_id: str
    job_type: str
    match_id: Optional[int]
    status: str
    priority: int = 50
    attempts: int = 0
    max_attempts: int = 3
    worker_id: Optional[str] = None
    parent_job_id: Optional[int] = None
    payload: Dict[str, Any] = field(default_factory=dict)
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    fingerprint: Optional[str] = None
