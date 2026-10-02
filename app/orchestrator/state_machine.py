class RunStatus:
    CREATED = "CREATED"
    RESOLVING = "RESOLVING"
    PLANNING = "PLANNING"
    QUEUED = "QUEUED"
    RESEARCHING = "RESEARCHING"
    VALIDATING = "VALIDATING"
    READY_FOR_ANALYSIS = "READY_FOR_ANALYSIS"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class TaskStatus:
    PENDING = "PENDING"
    QUEUED = "QUEUED"
    CLAIMED = "CLAIMED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    RETRY = "RETRY"
    CANCELLED = "CANCELLED"
    BLOCKED = "BLOCKED"


class OrchestratorStateMachine:
    ALLOWED_RUN_TRANSITIONS = {
        RunStatus.CREATED: [RunStatus.RESOLVING, RunStatus.FAILED, RunStatus.CANCELLED],
        RunStatus.RESOLVING: [RunStatus.PLANNING, RunStatus.BLOCKED, RunStatus.FAILED, RunStatus.CANCELLED],
        RunStatus.PLANNING: [RunStatus.QUEUED, RunStatus.FAILED, RunStatus.CANCELLED],
        RunStatus.QUEUED: [RunStatus.RESEARCHING, RunStatus.CANCELLED],
        RunStatus.RESEARCHING: [RunStatus.VALIDATING, RunStatus.BLOCKED, RunStatus.FAILED, RunStatus.CANCELLED],
        RunStatus.VALIDATING: [RunStatus.READY_FOR_ANALYSIS, RunStatus.BLOCKED, RunStatus.FAILED, RunStatus.CANCELLED],
        RunStatus.READY_FOR_ANALYSIS: [RunStatus.CANCELLED],
        RunStatus.BLOCKED: [RunStatus.PLANNING, RunStatus.RESEARCHING, RunStatus.CANCELLED],
        RunStatus.FAILED: [],
        RunStatus.CANCELLED: []
    }

    @classmethod
    def validate_run_transition(cls, current_status: str, new_status: str) -> bool:
        allowed = cls.ALLOWED_RUN_TRANSITIONS.get(current_status, [])
        if new_status not in allowed:
            raise ValueError(f"Neplatný přechod stavu Run: z '{current_status}' na '{new_status}'")
        return True