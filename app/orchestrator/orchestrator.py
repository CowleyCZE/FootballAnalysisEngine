import json
import sqlite3
import time
import uuid
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional

from app.orchestrator.config import PipelineConfig
from app.orchestrator.state_machine import MatchStateMachine, MatchState
from app.orchestrator.recovery import PipelineRecovery
from app.orchestrator.scheduler import DependencyScheduler
from app.jobs.queue import JobQueue
from app.jobs.models import JobStatus, JobPriority

logger = logging.getLogger(__name__)

class MasterOrchestrator:
    def __init__(self, db_path: str = "database/football.db", config_path: str = "config/pipeline.yaml"):
        self.db_path = db_path
        self.config = PipelineConfig.load(config_path)
        self.queue = JobQueue(db_path=db_path)
        self.state_machine = MatchStateMachine(db_path=db_path)
        self.recovery = PipelineRecovery(db_path=db_path, timeout_seconds=self.config["orchestrator"]["worker_timeout"])
        self.scheduler = DependencyScheduler(db_path=db_path)
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS pipeline_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL UNIQUE,
                    match_id INTEGER,
                    state TEXT NOT NULL,
                    cycle INTEGER NOT NULL DEFAULT 0,
                    max_cycles INTEGER NOT NULL DEFAULT 3,
                    started_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    finished_at TEXT,
                    error_text TEXT
                );
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS pipeline_state_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    old_state TEXT,
                    new_state TEXT NOT NULL,
                    reason TEXT,
                    created_at TEXT NOT NULL
                );
            """)
            conn.commit()

    def start_pipeline(self, match_id: int) -> str:
        run_id = f"{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_M{match_id}_{uuid.uuid4().hex[:4]}"
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        now_iso = datetime.now(timezone.utc).isoformat()

        cursor.execute(
            "INSERT INTO pipeline_runs (run_id, match_id, state, cycle, max_cycles, started_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (run_id, match_id, MatchState.NEW, 1, self.config["orchestrator"]["audit_max_cycles"], now_iso, now_iso)
        )
        conn.commit()
        conn.close()

        self.state_machine.transition_to(run_id, MatchState.DISCOVERY, "Initializing pipeline jobs")

        # Generování úvodních úloh
        self.queue.create_job("SEARCH", match_id, {"query": f"Match {match_id} lineups preview"}, priority=JobPriority.HIGH)
        self.queue.create_job("STATISTICS", match_id, {"type": "team_form"}, priority=JobPriority.NORMAL)

        return run_id

    def tick(self, run_id: str):
        self.recovery.recover_dead_workers_and_jobs()
        self.scheduler.update_blocked_jobs()

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute("SELECT match_id, state, cycle, max_cycles FROM pipeline_runs WHERE run_id = ?", (run_id,))
        run = cursor.fetchone()
        if not run:
            conn.close()
            return

        match_id = run["match_id"]
        state = run["state"]
        cycle = run["cycle"]
        max_cycles = run["max_cycles"]

        cursor.execute(
            "SELECT id, job_type, status, result_json FROM jobs WHERE match_id = ?",
            (match_id,),
        )
        jobs = cursor.fetchall()
        conn.close()

        if state == MatchState.DISCOVERY:
            if any(j["job_type"] == "SEARCH" and j["status"] == JobStatus.SUCCESS for j in jobs):
                self.state_machine.transition_to(run_id, MatchState.COLLECTING, "Search complete")
                self.queue.create_job("CRAWL", match_id, {"url": "https://example.com/lineups"}, priority=JobPriority.HIGH)

        elif state == MatchState.COLLECTING:
            if any(j["job_type"] == "CRAWL" and j["status"] == JobStatus.SUCCESS for j in jobs):
                self.state_machine.transition_to(run_id, MatchState.NORMALIZING, "Crawling complete")
                self.state_machine.transition_to(run_id, MatchState.CALCULATING, "Data normalized")

        elif state == MatchState.CALCULATING:
            if any(j["job_type"] == "STATISTICS" and j["status"] == JobStatus.SUCCESS for j in jobs):
                self.state_machine.transition_to(run_id, MatchState.ANALYZING, "Statistics ready")
                self.queue.create_job("AI_ANALYSIS", match_id, {"prompt": "Analyze form"}, priority=JobPriority.HIGH)

        elif state == MatchState.ANALYZING:
            ai_job = next((j for j in jobs if j["job_type"] == "AI_ANALYSIS" and j["status"] == JobStatus.SUCCESS), None)
            if ai_job:
                self.state_machine.transition_to(run_id, MatchState.AUDITING, "AI Analysis complete")
                ai_res = json.loads(ai_job["result_json"]) if ai_job["result_json"] else {}
                self.queue.create_job("AUDIT", match_id, {
                    "match_id": match_id,
                    "ai_analysis": ai_res,
                    "claims": [{"id": 1, "evidence": [{"id": 1, "published_at": datetime.now(timezone.utc).isoformat()}]}],
                    "statistics": {"wins": 6, "draws": 2, "losses": 2, "matches": 10},
                    "cycle": cycle
                }, priority=JobPriority.CRITICAL)

        elif state == MatchState.AUDITING:
            audit_job = next((j for j in jobs if j["job_type"] == "AUDIT" and j["status"] == JobStatus.SUCCESS), None)
            if audit_job:
                audit_res = json.loads(audit_job["result_json"]) if audit_job["result_json"] else {}
                status = audit_res.get("status")

                if status == "AUDIT_COMPLETE":
                    self.state_machine.transition_to(run_id, MatchState.FINALIZING, "Audit passed perfectly")
                    self.state_machine.transition_to(run_id, MatchState.COMPLETED, "Pipeline successful")
                elif status == "RESEARCH_REQUIRED":
                    if cycle < max_cycles:
                        self.state_machine.transition_to(run_id, MatchState.RESEARCHING, f"Research required for cycle {cycle}")
                        self.queue.create_job("RESEARCH", match_id, {"reason": "Verify injured players"}, priority=JobPriority.HIGH)
                    else:
                        self.state_machine.transition_to(run_id, MatchState.UNRESOLVED, f"Max cycles ({max_cycles}) reached with pending issues")

        elif state == MatchState.RESEARCHING:
            if any(j["job_type"] == "RESEARCH" and j["status"] == JobStatus.SUCCESS for j in jobs):
                conn = sqlite3.connect(self.db_path)
                cursor = conn.cursor()
                cursor.execute("UPDATE pipeline_runs SET cycle = cycle + 1 WHERE run_id = ?", (run_id,))
                conn.commit()
                conn.close()

                self.state_machine.transition_to(run_id, MatchState.REANALYZING, "Research data collected")
                self.queue.create_job("AI_ANALYSIS", match_id, {"prompt": "Re-analyze with new evidence"}, priority=JobPriority.HIGH)
                self.state_machine.transition_to(run_id, MatchState.ANALYZING, "Re-running AI Analysis")

        elif state == MatchState.FINALIZING:
            if self._are_all_jobs_completed(run_id):
                self.state_machine.transition_to(run_id, MatchState.COMPLETED, "All jobs completed")

    def _are_all_jobs_completed(self, run_id: str) -> bool:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT status FROM jobs
            WHERE match_id = (SELECT match_id FROM pipeline_runs WHERE run_id = ?)
            """,
            (run_id,),
        )
        rows = cursor.fetchall()
        conn.close()
        if not rows:
            return False
        terminal = {JobStatus.SUCCESS, JobStatus.FAILED, JobStatus.CANCELLED}
        return all(row["status"] in terminal for row in rows)
