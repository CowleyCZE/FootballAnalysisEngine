from enum import IntEnum

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
