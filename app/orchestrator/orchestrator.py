import json
import logging
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from app.jobs.models import JobPriority, JobStatus
from app.jobs.queue import JobQueue
from app.orchestrator.config import PipelineConfig
from app.orchestrator.recovery import PipelineRecovery
from app.orchestrator.scheduler import DependencyScheduler
from app.orchestrator.state_machine import MatchState, MatchStateMachine

logger = logging.getLogger(__name__)


class MasterOrchestrator:
    """Single source of truth for the autonomous match-analysis pipeline."""

    def __init__(self, db_path: str = "database/football.db", config_path: str = "config/pipeline.yaml"):
        self.db_path = db_path
        self.config = PipelineConfig.load(config_path)
        self.queue = JobQueue(db_path)
        self.state_machine = MatchStateMachine(db_path)
        self.recovery = PipelineRecovery(db_path=db_path, timeout_seconds=int(self.config["orchestrator"]["worker_timeout"]))
        self.scheduler = DependencyScheduler(db_path=db_path)
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    pipeline_version TEXT,
                    config_hash TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS pipeline_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL UNIQUE,
                    match_id INTEGER,
                    state TEXT NOT NULL,
                    cycle INTEGER NOT NULL DEFAULT 1,
                    max_cycles INTEGER NOT NULL DEFAULT 3,
                    started_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    finished_at TEXT,
                    error_text TEXT
                );
                CREATE TABLE IF NOT EXISTS pipeline_state_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    old_state TEXT,
                    new_state TEXT NOT NULL,
                    reason TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS system_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    run_id TEXT,
                    job_id TEXT,
                    worker_id TEXT,
                    payload_json TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                """
            )

    def _event(self, event_type: str, run_id: Optional[str], job_id: Optional[str] = None, payload: Optional[Dict[str, Any]] = None) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("INSERT INTO system_events(event_type, run_id, job_id, payload_json) VALUES(?,?,?,?)", (event_type, run_id, job_id, json.dumps(payload or {}, sort_keys=True)))

    def _match_context(self, match_id: int) -> Dict[str, Any]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT m.id, m.scheduled_at, m.competition, m.season,
                       m.home_team_id, m.away_team_id,
                       ht.name AS home_team, at.name AS away_team
                FROM matches m
                JOIN teams ht ON ht.id=m.home_team_id
                JOIN teams at ON at.id=m.away_team_id
                WHERE m.id=?
                """,
                (match_id,),
            ).fetchone()
        if not row:
            raise ValueError(f"Match {match_id} does not exist in database")
        data = dict(row)
        data["cutoff_datetime"] = data.get("scheduled_at") or self._now()
        return data

    def start_pipeline(self, match_id: int) -> str:
        match = self._match_context(match_id)
        run_id = f"{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_M{match_id}_{uuid.uuid4().hex[:6]}"
        now = self._now()
        max_cycles = int(self.config["orchestrator"]["audit_max_cycles"])
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("INSERT INTO runs(run_id,status,started_at,pipeline_version) VALUES(?,?,?,?)", (run_id, "RUNNING", now, "11.5"))
            run_db_id = cursor.lastrowid
            cursor.execute(
                "INSERT INTO pipeline_runs(run_id,match_id,state,cycle,max_cycles,started_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                (run_id, match_id, MatchState.NEW, 1, max_cycles, now, now),
            )

        self._event("PIPELINE_CREATED", run_id, payload={"match_id": match_id})
        self.state_machine.transition_to(run_id, MatchState.DISCOVERY, "Pipeline initialized")

        search_query = f"{match['home_team']} {match['away_team']} {match['competition']} lineup injuries form"
        self.queue.create_job("SEARCH", match_id, {"query": search_query, "run_id": run_id}, priority=JobPriority.HIGH, run_id=run_id)
        self.queue.create_job(
            "STATISTICS", match_id,
            {
                "match_id": match_id,
                "run_id": run_id,
                "run_db_id": run_db_id,
                "home_team_id": match["home_team_id"],
                "away_team_id": match["away_team_id"],
                "cutoff_datetime": match["cutoff_datetime"],
                "scope": "team_form",
            },
            priority=JobPriority.NORMAL,
            run_id=run_id,
        )
        return run_id

    def tick(self, run_id: str) -> None:
        self.recovery.recover_dead_workers_and_jobs()
        self.scheduler.update_blocked_jobs()
        run = self._get_run(run_id)
        if not run or run["state"] in (MatchState.COMPLETED, MatchState.UNRESOLVED, MatchState.FAILED):
            return
        jobs = self._jobs_for_run(run_id)
        state, match_id, cycle, max_cycles = run["state"], run["match_id"], run["cycle"], run["max_cycles"]

        failed_required = [j for j in jobs if j["status"] == JobStatus.FAILED and j["job_type"] not in {"REPORT"}]
        if failed_required and state not in (MatchState.RESEARCHING, MatchState.REANALYZING):
            self._fail(run_id, f"Required job failed: {failed_required[0]['job_type']}")
            return

        if state == MatchState.DISCOVERY:
            search = self._latest_success(jobs, "SEARCH")
            if search:
                results = self._result(search)
                urls = list(dict.fromkeys(r.get("url") for r in results.get("results", []) if r.get("url")))
                if not urls:
                    self._fail(run_id, "Search returned no crawlable URLs")
                    return
                for url in urls:
                    self.queue.create_job("CRAWL", match_id, {"url": url}, priority=JobPriority.HIGH, run_id=run_id)
                self.state_machine.transition_to(run_id, MatchState.COLLECTING, "Search complete; crawl jobs scheduled")

        elif state == MatchState.COLLECTING:
            crawl_jobs = [j for j in jobs if j["job_type"] == "CRAWL"]
            if crawl_jobs and all(j["status"] == JobStatus.SUCCESS for j in crawl_jobs):
                self.state_machine.transition_to(run_id, MatchState.NORMALIZING, "Crawling complete")
                self.state_machine.transition_to(run_id, MatchState.CALCULATING, "Normalization complete")

        elif state == MatchState.CALCULATING:
            if self._latest_success(jobs, "STATISTICS"):
                self.state_machine.transition_to(run_id, MatchState.ANALYZING, "Statistics ready")
                self.queue.create_job("AI_ANALYSIS", match_id, {"match_id": match_id, "run_id": run_id, "mode": "evidence_first"}, priority=JobPriority.HIGH, run_id=run_id)

        elif state == MatchState.ANALYZING:
            ai_job = self._latest_success(jobs, "AI_ANALYSIS")
            if ai_job:
                self.state_machine.transition_to(run_id, MatchState.AUDITING, "AI analysis complete")
                stats_job = self._latest_success(jobs, "STATISTICS")
                self.queue.create_job(
                    "AUDIT", match_id,
                    {"match_id": match_id, "run_id": run_id, "cycle": cycle, "ai_analysis": self._result(ai_job), "statistics": self._result(stats_job) if stats_job else {}},
                    priority=JobPriority.CRITICAL, run_id=run_id,
                )

        elif state == MatchState.AUDITING:
            audit_job = self._latest_success(jobs, "AUDIT")
            if audit_job:
                audit = self._result(audit_job)
                status = audit.get("status") or audit.get("pipeline_status")
                if status in {"AUDIT_COMPLETE", "PASS", "OK", "COMPLETED"} and not audit.get("research_required"):
                    self.state_machine.transition_to(run_id, MatchState.FINALIZING, "Audit passed")
                elif status in {"RESEARCH_REQUIRED", "REQUIRES_RESEARCH"} or audit.get("research_required"):
                    if cycle >= max_cycles:
                        self.state_machine.transition_to(run_id, MatchState.UNRESOLVED, f"Maximum audit cycles ({max_cycles}) reached")
                    else:
                        self.state_machine.transition_to(run_id, MatchState.RESEARCHING, f"Audit requires research for cycle {cycle}")
                        self.queue.create_job("RESEARCH", match_id, {"match_id": match_id, "run_id": run_id, "reason": audit.get("research_jobs") or audit.get("issues") or {"reason": "audit follow-up"}, "cycle": cycle + 1}, priority=JobPriority.HIGH, run_id=run_id)
                else:
                    self.state_machine.transition_to(run_id, MatchState.UNRESOLVED, "Audit did not produce a resolvable terminal state")

        elif state == MatchState.RESEARCHING:
            if self._latest_success(jobs, "RESEARCH"):
                with sqlite3.connect(self.db_path) as conn:
                    conn.execute("UPDATE pipeline_runs SET cycle=cycle+1, updated_at=? WHERE run_id=?", (self._now(), run_id))
                self.state_machine.transition_to(run_id, MatchState.REANALYZING, "Research completed")
                self.queue.create_job("AI_ANALYSIS", match_id, {"match_id": match_id, "run_id": run_id, "mode": "reanalysis"}, priority=JobPriority.HIGH, run_id=run_id)
                self.state_machine.transition_to(run_id, MatchState.ANALYZING, "Re-analysis scheduled")

        elif state == MatchState.FINALIZING and self._run_is_terminal_ready(run_id):
            self._finish(run_id, MatchState.COMPLETED, "All required jobs completed")

    def _get_run(self, run_id: str):
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            return conn.execute("SELECT * FROM pipeline_runs WHERE run_id=?", (run_id,)).fetchone()

    def _jobs_for_run(self, run_id: str):
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            return conn.execute("SELECT * FROM jobs WHERE run_id=? ORDER BY id", (run_id,)).fetchall()

    @staticmethod
    def _latest_success(jobs, job_type: str):
        matches = [j for j in jobs if j["job_type"] == job_type and j["status"] == JobStatus.SUCCESS]
        return matches[-1] if matches else None

    @staticmethod
    def _result(job) -> Dict[str, Any]:
        if not job or not job["result_json"]:
            return {}
        try:
            return json.loads(job["result_json"])
        except (TypeError, json.JSONDecodeError):
            return {}

    def _run_is_terminal_ready(self, run_id: str) -> bool:
        jobs = self._jobs_for_run(run_id)
        return bool(jobs) and all(j["status"] in {JobStatus.SUCCESS, JobStatus.CANCELLED} for j in jobs)

    def _fail(self, run_id: str, reason: str) -> None:
        self.state_machine.transition_to(run_id, MatchState.FAILED, reason)
        self._finish_metadata(run_id, MatchState.FAILED, reason)

    def _finish(self, run_id: str, state: str, reason: str) -> None:
        self.state_machine.transition_to(run_id, state, reason)
        self._finish_metadata(run_id, state, reason)

    def _finish_metadata(self, run_id: str, state: str, reason: str) -> None:
        now = self._now()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("UPDATE pipeline_runs SET finished_at=?, updated_at=?, error_text=? WHERE run_id=?", (now, now, None if state == MatchState.COMPLETED else reason, run_id))
            conn.execute("UPDATE runs SET status=?, finished_at=? WHERE run_id=?", (state, now, run_id))
        self._event("PIPELINE_FINISHED", run_id, payload={"state": state, "reason": reason})

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()
