from datetime import datetime, timezone
import json
import sqlite3
import logging
from typing import Optional

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
    """Canonical pipeline state machine and immutable state-history writer."""

    ALLOWED_TRANSITIONS = {
        MatchState.NEW: [MatchState.DISCOVERY, MatchState.FAILED, MatchState.UNRESOLVED],
        MatchState.DISCOVERY: [MatchState.COLLECTING, MatchState.FAILED, MatchState.UNRESOLVED],
        MatchState.COLLECTING: [MatchState.NORMALIZING, MatchState.FAILED, MatchState.UNRESOLVED],
        MatchState.NORMALIZING: [MatchState.CALCULATING, MatchState.FAILED, MatchState.UNRESOLVED],
        MatchState.CALCULATING: [MatchState.ANALYZING, MatchState.FAILED, MatchState.UNRESOLVED],
        MatchState.ANALYZING: [MatchState.AUDITING, MatchState.FAILED, MatchState.UNRESOLVED],
        MatchState.AUDITING: [MatchState.FINALIZING, MatchState.RESEARCHING, MatchState.UNRESOLVED, MatchState.FAILED],
        MatchState.RESEARCHING: [MatchState.REANALYZING, MatchState.FAILED, MatchState.UNRESOLVED],
        MatchState.REANALYZING: [MatchState.ANALYZING, MatchState.AUDITING, MatchState.FAILED, MatchState.UNRESOLVED],
        MatchState.FINALIZING: [MatchState.COMPLETED, MatchState.FAILED, MatchState.UNRESOLVED],
        MatchState.COMPLETED: [],
        MatchState.UNRESOLVED: [],
        MatchState.FAILED: [],
    }

    def __init__(self, db_path: str = "database/football.db"):
        self.db_path = db_path

    def transition_to(self, run_id: str, new_state: str, reason: str = "") -> bool:
        """Atomically validate, update, audit and persist one state transition."""
        now_iso = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(self.db_path, timeout=30) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT state FROM pipeline_runs WHERE run_id = ?", (run_id,)).fetchone()
            if not row:
                return False

            current_state = row["state"]
            if new_state == current_state:
                return False
            if new_state not in self.ALLOWED_TRANSITIONS.get(current_state, []):
                logger.error("Invalid state transition requested for %s: %s -> %s", run_id, current_state, new_state)
                return False

            finished_at = now_iso if new_state in (MatchState.COMPLETED, MatchState.UNRESOLVED, MatchState.FAILED) else None
            conn.execute(
                "UPDATE pipeline_runs SET state=?, updated_at=?, finished_at=CASE WHEN ? IS NOT NULL THEN ? ELSE finished_at END WHERE run_id=? AND state=?",
                (new_state, now_iso, finished_at, finished_at, run_id, current_state),
            )
            conn.execute(
                "INSERT INTO pipeline_state_history(run_id, old_state, new_state, reason, created_at) VALUES(?,?,?,?,?)",
                (run_id, current_state, new_state, reason, now_iso),
            )
            conn.execute(
                "INSERT INTO system_events(event_type, run_id, payload_json, created_at) VALUES(?,?,?,?)",
                ("PIPELINE_STATE_CHANGED", run_id, json.dumps({"old_state": current_state, "new_state": new_state, "reason": reason}, sort_keys=True), now_iso),
            )
        return True

    def current_state(self, run_id: str) -> Optional[str]:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute("SELECT state FROM pipeline_runs WHERE run_id=?", (run_id,)).fetchone()
        return row[0] if row else None
