from datetime import datetime, timezone
import sqlite3
import logging

logger = logging.getLogger(__name__)

class MatchState:
    NEW = "NEW"
    DISCOVERY = "DISCOVERY"
    COLLECTING = "COLLECTING"
    NORMALIZING = "NORMALIZING"
    CALCULATING = "CALCULATING"
    ANALYZING = "ANALYZING"
    AUDITING = "AUDITING"
    RESEARCHING = "RESEARCHING"
    REANALYZING = "REANALYZING"
    FINALIZING = "FINALIZING"
    COMPLETED = "COMPLETED"
    UNRESOLVED = "UNRESOLVED"
    FAILED = "FAILED"

class MatchStateMachine:
    ALLOWED_TRANSITIONS = {
        MatchState.NEW: [MatchState.DISCOVERY, MatchState.FAILED],
        MatchState.DISCOVERY: [MatchState.COLLECTING, MatchState.FAILED],
        MatchState.COLLECTING: [MatchState.NORMALIZING, MatchState.FAILED],
        MatchState.NORMALIZING: [MatchState.CALCULATING, MatchState.FAILED],
        MatchState.CALCULATING: [MatchState.ANALYZING, MatchState.FAILED],
        MatchState.ANALYZING: [MatchState.AUDITING, MatchState.FAILED],
        MatchState.AUDITING: [MatchState.FINALIZING, MatchState.RESEARCHING, MatchState.UNRESOLVED, MatchState.FAILED],
        MatchState.RESEARCHING: [MatchState.REANALYZING, MatchState.FAILED],
        MatchState.REANALYZING: [MatchState.ANALYZING, MatchState.AUDITING, MatchState.FAILED],
        MatchState.FINALIZING: [MatchState.COMPLETED, MatchState.FAILED],
        MatchState.COMPLETED: [],
        MatchState.UNRESOLVED: [],
        MatchState.FAILED: []
    }

    def __init__(self, db_path: str = "database/football.db"):
        self.db_path = db_path

    def transition_to(self, run_id: str, new_state: str, reason: str = "") -> bool:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute("SELECT state FROM pipeline_runs WHERE run_id = ?", (run_id,))
        row = cursor.fetchone()
        if not row:
            conn.close()
            return False

        current_state = row["state"]
        allowed = self.ALLOWED_TRANSITIONS.get(current_state, [])

        if new_state not in allowed:
            logger.error(f"Invalid state transition requested for {run_id}: {current_state} -> {new_state}")
            conn.close()
            return False

        now_iso = datetime.now(timezone.utc).isoformat()
        cursor.execute(
            "UPDATE pipeline_runs SET state = ?, updated_at = ? WHERE run_id = ?",
            (new_state, now_iso, run_id)
        )
        cursor.execute(
            "INSERT INTO pipeline_state_history (run_id, old_state, new_state, reason, created_at) VALUES (?, ?, ?, ?, ?)",
            (run_id, current_state, new_state, reason, now_iso)
        )

        conn.commit()
        conn.close()
        return True
