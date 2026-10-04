import json
import logging
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from app.jobs.models import JobPriority, JobStatus
from app.jobs.queue import JobQueue
from app.orchestrator.config import PipelineConfig
from app.orchestrator.policies import ResearchPolicy
from app.orchestrator.recovery import PipelineRecovery
from app.orchestrator.research_planner import ResearchPlanner
from app.orchestrator.scheduler import DependencyScheduler
from app.orchestrator.state_machine import MatchState, MatchStateMachine
from app.orchestrator.models import MatchIdentity

logger = logging.getLogger(__name__)


class MasterOrchestrator:
    """Single source of truth for the autonomous match-analysis pipeline."""

    def __init__(self, db_path: str = "database/football.db", config_path: str = "config/pipeline.yaml"):
        self.db_path = db_path
        self.config = PipelineConfig.load(config_path)
        self.queue = JobQueue(db_path)
        self.state_machine = MatchStateMachine(db_path)
        self.recovery = PipelineRecovery(
            db_path=db_path,
            timeout_seconds=int(self.config["orchestrator"]["worker_timeout"]),
        )
        self.scheduler = DependencyScheduler(db_path=db_path)
        self.research_planner = ResearchPlanner()
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
                CREATE TABLE IF NOT EXISTS research_tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    run_db_id INTEGER,
                    match_id INTEGER NOT NULL,
                    task_uuid TEXT NOT NULL,
                    domain TEXT NOT NULL,
                    task_type TEXT NOT NULL,
                    description TEXT NOT NULL,
                    required INTEGER NOT NULL DEFAULT 0,
                    priority INTEGER NOT NULL DEFAULT 50,
                    capabilities_json TEXT NOT NULL DEFAULT '[]',
                    data_cutoff_at TEXT NOT NULL,
                    home_team TEXT NOT NULL,
                    away_team TEXT NOT NULL,
                    competition TEXT NOT NULL,
                    scheduled_at TEXT NOT NULL,
                    venue TEXT,
                    status TEXT NOT NULL DEFAULT 'PLANNED',
                    attempt_number INTEGER NOT NULL DEFAULT 1,
                    job_id TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(run_id, task_uuid)
                );
                CREATE INDEX IF NOT EXISTS idx_research_tasks_run ON research_tasks(run_id);
                CREATE INDEX IF NOT EXISTS idx_research_tasks_status ON research_tasks(run_id, status);
                """
            )

    def _event(self, event_type: str, run_id: Optional[str], job_id: Optional[str] = None, payload: Optional[Dict[str, Any]] = None) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO system_events(event_type, run_id, job_id, payload_json) VALUES(?,?,?,?)",
                (event_type, run_id, job_id, json.dumps(payload or {}, sort_keys=True)),
            )

    def _match_context(self, match_id: int) -> Dict[str, Any]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT m.id, m.scheduled_at, m.competition, m.season, m.venue,
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

    def _match_identity(self, match: Dict[str, Any]) -> MatchIdentity:
        scheduled_at = datetime.fromisoformat(match["scheduled_at"])
        cutoff = datetime.fromisoformat(match["cutoff_datetime"])
        return MatchIdentity(
            match_id=int(match["id"]),
            home_team_id=int(match["home_team_id"]),
            away_team_id=int(match["away_team_id"]),
            competition_id=None,
            scheduled_at=scheduled_at,
            data_cutoff_at=cutoff,
        )

    def start_pipeline(self, match_id: int) -> str:
        match = self._match_context(match_id)
        run_id = f"{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_M{match_id}_{uuid.uuid4().hex[:6]}"
        now = self._now()
        max_cycles = int(self.config["orchestrator"]["audit_max_cycles"])
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO runs(run_id,status,started_at,pipeline_version) VALUES(?,?,?,?)",
                (run_id, "RUNNING", now, "12.0"),
            )
            run_db_id = cursor.lastrowid
            cursor.execute(
                "INSERT INTO pipeline_runs(run_id,match_id,state,cycle,max_cycles,started_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                (run_id, match_id, MatchState.NEW, 1, max_cycles, now, now),
            )

        self._event("PIPELINE_CREATED", run_id, payload={"match_id": match_id})
        self.state_machine.transition_to(run_id, MatchState.DISCOVERY, "Pipeline initialized")

        identity = self._match_identity(match)
        self._create_research_plan(run_id, run_db_id, match, identity, cycle=1)
        self.queue.create_job(
            "STATISTICS",
            match_id,
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
        self._event("RESEARCH_PLAN_CREATED", run_id, payload={"cycle": 1, "tasks": self._research_task_count(run_id)})
        return run_id

    def _create_research_plan(self, run_id: str, run_db_id: int, match: Dict[str, Any], identity: MatchIdentity, cycle: int, domains: Optional[list[str]] = None) -> list[Dict[str, Any]]:
        plan = self.research_planner.create_plan(identity)
        if domains:
            allowed = set(domains)
            plan = [task for task in plan if task.domain in allowed]

        created: list[Dict[str, Any]] = []
        for requirement in plan:
            task_id = self._upsert_research_task(run_id, run_db_id, match, requirement, cycle)
            payload = self._research_task_payload(run_id, run_db_id, match, requirement, task_id, cycle)
            job_id = self.queue.create_job(
                "RESEARCH",
                int(match["id"]),
                payload,
                priority=int(requirement.priority),
                run_id=run_id,
            )
            if job_id is None:
                job_id = self._existing_task_job(run_id, task_id)
            if job_id:
                with sqlite3.connect(self.db_path) as conn:
                    conn.execute(
                        "UPDATE research_tasks SET job_id=?, status='QUEUED', updated_at=? WHERE id=?",
                        (job_id, self._now(), task_id),
                    )
                self._event("RESEARCH_TASK_QUEUED", run_id, job_id=job_id, payload={"task_id": task_id, "domain": requirement.domain, "cycle": cycle})
            created.append({"task_id": task_id, "job_id": job_id, "domain": requirement.domain, "required": requirement.required})
        return created

    def _upsert_research_task(self, run_id: str, run_db_id: int, match: Dict[str, Any], requirement, cycle: int) -> int:
        task_uuid = requirement.task_uuid + f"-C{cycle}"
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO research_tasks(
                    run_id, run_db_id, match_id, task_uuid, domain, task_type, description,
                    required, priority, capabilities_json, data_cutoff_at, home_team, away_team,
                    competition, scheduled_at, venue, status, attempt_number
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(run_id, task_uuid) DO UPDATE SET
                    description=excluded.description,
                    required=excluded.required,
                    priority=excluded.priority,
                    capabilities_json=excluded.capabilities_json,
                    data_cutoff_at=excluded.data_cutoff_at,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (
                    run_id,
                    run_db_id,
                    int(match["id"]),
                    task_uuid,
                    requirement.domain,
                    requirement.task_type,
                    requirement.description,
                    1 if requirement.required else 0,
                    int(requirement.priority),
                    json.dumps(requirement.capabilities_required),
                    match["cutoff_datetime"],
                    match["home_team"],
                    match["away_team"],
                    match["competition"],
                    match["scheduled_at"],
                    match.get("venue"),
                    "PLANNED",
                    1,
                ),
            )
            row = cursor.execute("SELECT id FROM research_tasks WHERE run_id=? AND task_uuid=?", (run_id, task_uuid)).fetchone()
            return int(row[0])

    def _research_task_payload(self, run_id: str, run_db_id: int, match: Dict[str, Any], requirement, task_id: int, cycle: int) -> Dict[str, Any]:
        return {
            "run_id": run_id,
            "run_db_id": run_db_id,
            "task_id": task_id,
            "match_id": int(match["id"]),
            "domain": requirement.domain,
            "task_type": requirement.task_type,
            "description": requirement.description,
            "required": requirement.required,
            "priority": requirement.priority,
            "capabilities_required": requirement.capabilities_required,
            "match": match,
            "cycle": cycle,
            "cutoff_datetime": match["cutoff_datetime"],
        }

    def _existing_task_job(self, run_id: str, task_id: int) -> Optional[str]:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute("SELECT job_id FROM research_tasks WHERE run_id=? AND id=?", (run_id, task_id)).fetchone()
            return row[0] if row and row[0] else None

    def _research_task_count(self, run_id: str) -> int:
        with sqlite3.connect(self.db_path) as conn:
            return int(conn.execute("SELECT COUNT(*) FROM research_tasks WHERE run_id=?", (run_id,)).fetchone()[0])

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
            if self._research_plan_ready(run_id):
                self.state_machine.transition_to(run_id, MatchState.COLLECTING, "Research plan completed")

        elif state == MatchState.COLLECTING:
            if self._research_plan_ready(run_id) and self._latest_success(jobs, "STATISTICS"):
                self.state_machine.transition_to(run_id, MatchState.NORMALIZING, "Research and statistics collected")
                self.state_machine.transition_to(run_id, MatchState.CALCULATING, "Normalization complete")

        elif state == MatchState.CALCULATING:
            if self._latest_success(jobs, "STATISTICS") and self._research_plan_ready(run_id):
                self.state_machine.transition_to(run_id, MatchState.ANALYZING, "Statistics and research evidence ready")
                self.queue.create_job("AI_ANALYSIS", match_id, self._ai_payload(run_id, match_id, mode="evidence_first"), priority=JobPriority.HIGH, run_id=run_id)

        elif state == MatchState.ANALYZING:
            ai_job = self._latest_success(jobs, "AI_ANALYSIS")
            if ai_job:
                self.state_machine.transition_to(run_id, MatchState.AUDITING, "AI analysis complete")
                stats_job = self._latest_success(jobs, "STATISTICS")
                self.queue.create_job(
                    "AUDIT", match_id,
                    {"match_id": match_id, "run_id": run_id, "cycle": cycle, "ai_analysis": self._result(ai_job), "claims": self._claims(run_id), "statistics": self._result(stats_job) if stats_job else {}},
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
                        domains = self._research_domains_from_audit(audit)
                        match = self._match_context(match_id)
                        self._create_research_plan(run_id, self._run_db_id(run_id), match, self._match_identity(match), cycle=cycle + 1, domains=domains)
                else:
                    self.state_machine.transition_to(run_id, MatchState.UNRESOLVED, "Audit did not produce a resolvable terminal state")

        elif state == MatchState.RESEARCHING:
            if self._research_plan_ready(run_id, cycle=cycle + 1):
                with sqlite3.connect(self.db_path) as conn:
                    conn.execute("UPDATE pipeline_runs SET cycle=cycle+1, updated_at=? WHERE run_id=?", (self._now(), run_id))
                self.state_machine.transition_to(run_id, MatchState.REANALYZING, "Research completed")
                self.queue.create_job("AI_ANALYSIS", match_id, self._ai_payload(run_id, match_id, mode="reanalysis"), priority=JobPriority.HIGH, run_id=run_id)
                self.state_machine.transition_to(run_id, MatchState.ANALYZING, "Re-analysis scheduled")

        elif state == MatchState.FINALIZING and self._run_is_terminal_ready(run_id):
            self._finish(run_id, MatchState.COMPLETED, "All required jobs completed")

    def _research_plan_ready(self, run_id: str, cycle: Optional[int] = None) -> bool:
        where = "run_id=?"
        params: list[Any] = [run_id]
        if cycle is not None:
            where += " AND task_uuid LIKE ?"
            params.append(f"%-C{cycle}")
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(f"SELECT required, status FROM research_tasks WHERE {where}", params).fetchall()
        required = [row for row in rows if int(row[0]) == 1]
        if not required:
            return False
        return all(row[1] in {"SUCCESS", "PARTIAL", "NO_RESULT", "CONFLICTED"} for row in required)

    def _run_db_id(self, run_id: str) -> int:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute("SELECT id FROM runs WHERE run_id=?", (run_id,)).fetchone()
        if not row:
            raise ValueError(f"Run {run_id} not found")
        return int(row[0])

    def _ai_payload(self, run_id: str, match_id: int, mode: str) -> Dict[str, Any]:
        stats_job = self._latest_success(self._jobs_for_run(run_id), "STATISTICS")
        return {"match_id": match_id, "run_id": run_id, "mode": mode, "match": self._match_context(match_id), "statistics": self._result(stats_job) if stats_job else {}, "claims": self._claims(run_id), "conflicts": self._conflicts(run_id)}

    def _claims(self, run_id: str) -> list[Dict[str, Any]]:
        claims: list[Dict[str, Any]] = []
        for job in self._jobs_for_run(run_id):
            if job["job_type"] == "RESEARCH" and job["status"] == JobStatus.SUCCESS:
                claims.extend(self._result(job).get("claims") or [])
        return claims

    def _conflicts(self, run_id: str) -> list[Dict[str, Any]]:
        return [c for c in self._claims(run_id) if str(c.get("status")) == "CONFLICTED"]

    @staticmethod
    def _research_domains_from_audit(audit: Dict[str, Any]) -> list[str]:
        requested = audit.get("research_jobs") or audit.get("domains") or []
        if isinstance(requested, dict):
            requested = list(requested.keys())
        if isinstance(requested, str):
            requested = [requested]
        valid = set(ResearchPolicy.REQUIRED_DOMAINS + ResearchPolicy.OPTIONAL_DOMAINS)
        domains = [str(item) for item in requested if str(item) in valid]
        return domains or ResearchPolicy.REQUIRED_DOMAINS

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
