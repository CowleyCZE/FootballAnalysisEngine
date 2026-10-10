import json
import sqlite3
import uuid
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List

from app.orchestrator.config import PipelineConfig
from app.orchestrator.state_machine import MatchStateMachine, MatchState
from app.orchestrator.recovery import PipelineRecovery
from app.orchestrator.scheduler import DependencyScheduler
from app.orchestrator.match_resolver import MatchResolver, MatchNotFoundException, AmbiguousMatchException, parse_to_utc
from app.orchestrator.research_planner import ResearchPlanner
from app.orchestrator.coverage import CoverageEngine
from app.orchestrator.models import AnalysisRequest, MatchIdentity, TaskRequirement
from app.jobs.queue import JobQueue
from app.jobs.models import JobStatus, JobPriority
from app.database.connection import init_database_schema

logger = logging.getLogger(__name__)

_TASK_TYPE_TO_JOB_TYPE = {
    "FACT_COLLECTION": "RESEARCH",
    "STAT_COLLECTION": "STATISTICS",
    "NEWS_COLLECTION": "RESEARCH",
}


class MasterOrchestrator:
    """
    Hlavní orchestrátor pipeline — řídí celý životní cyklus analýzy zápasu.
    Start pipeline jde přes: Match Identity → Research Planner → Research Tasks (joby).
    """

    def __init__(self, db_path: str = "database/football.db", config_path: str = "config/pipeline.yaml"):
        self.db_path = db_path
        self.config = PipelineConfig.load(config_path)
        self.queue = JobQueue(db_path=db_path)
        self.state_machine = MatchStateMachine(db_path=db_path)
        self.recovery = PipelineRecovery(db_path=db_path, timeout_seconds=self.config["orchestrator"]["worker_timeout"])
        self.scheduler = DependencyScheduler(db_path=db_path)
        self.planner = ResearchPlanner()
        self.coverage_engine = CoverageEngine(db_path=db_path)
        init_database_schema(db_path)

    def _get_match_identity_from_id(self, match_id: int, data_cutoff_at: Optional[datetime] = None) -> Optional[MatchIdentity]:
        """Načte MatchIdentity z databáze na základě match_id."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        try:
            cursor.execute("""
                SELECT m.id as match_id, m.home_team_id, m.away_team_id,
                       m.competition_id, m.scheduled_at, m.venue, m.status,
                       th.name as home_team, ta.name as away_team, COALESCE(c.name, m.competition, '') as competition
                FROM matches m
                LEFT JOIN teams th ON m.home_team_id = th.id
                LEFT JOIN teams ta ON m.away_team_id = ta.id
                LEFT JOIN competitions c ON m.competition_id = c.id
                WHERE m.id = ?
            """, (match_id,))
            row = cursor.fetchone()
            if not row:
                return None

            match_status = row["status"] if ("status" in row.keys() and row["status"]) else None
            if match_status != "RESOLVED":
                return None

            scheduled_str = row["scheduled_at"]
            if not scheduled_str:
                return None
            try:
                scheduled_dt = parse_to_utc(scheduled_str)
            except Exception:
                return None

            cutoff_dt = None
            if data_cutoff_at is not None:
                cutoff_dt = parse_to_utc(data_cutoff_at)

            return MatchIdentity(
                match_id=row["match_id"],
                home_team_id=row["home_team_id"],
                away_team_id=row["away_team_id"],
                competition_id=row["competition_id"],
                home_team=row["home_team"] or f"Team_{row['home_team_id']}",
                away_team=row["away_team"] or f"Team_{row['away_team_id']}",
                competition=row["competition"] or "Unknown Competition",
                scheduled_at=scheduled_dt,
                data_cutoff_at=cutoff_dt,
                venue=row["venue"] if "venue" in row.keys() else None,
                status=match_status,
            )
        finally:
            conn.close()

    def _dispatch_research_tasks(self, tasks: List[TaskRequirement], match_id: int, run_id: str, match_identity: MatchIdentity) -> List[str]:
        """Persist ResearchTasks and jobs in one SQLite transaction with explicit job dependencies."""
        created = []
        task_uuid_to_job_id = {}
        task_uuid_to_job_pk = {}

        with sqlite3.connect(self.db_path, timeout=30) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT id FROM runs WHERE run_id=?", (run_id,)).fetchone()
            if not row:
                raise KeyError(run_id)
            run_db_id = int(row["id"])

            for task in tasks:
                row = conn.execute("SELECT id, job_id FROM research_tasks WHERE run_id=? AND task_uuid=?", (run_id, task.task_uuid)).fetchone()
                if row and row["job_id"]:
                    created.append(row["job_id"])
                    job_pk = conn.execute("SELECT id FROM jobs WHERE job_id=?", (row["job_id"],)).fetchone()[0]
                    task_uuid_to_job_id[task.task_uuid] = row["job_id"]
                    task_uuid_to_job_pk[task.task_uuid] = int(job_pk)
                    continue

                cutoff_iso = match_identity.data_cutoff_at.isoformat() if match_identity.data_cutoff_at else None

                if row:
                    task_id = int(row["id"])
                else:
                    cur = conn.execute("INSERT INTO research_tasks(run_id,run_db_id,match_id,task_uuid,domain,task_type,description,required,priority,capabilities_json,data_cutoff_at,home_team,away_team,competition,scheduled_at,venue,status) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (run_id,run_db_id,match_id,task.task_uuid,task.domain,task.task_type,task.description,1 if task.required else 0,task.priority,json.dumps(task.capabilities_required),cutoff_iso,match_identity.home_team,match_identity.away_team,match_identity.competition,match_identity.scheduled_at.isoformat(),match_identity.venue,"PLANNED"))
                    task_id = int(cur.lastrowid)

                job_type = _TASK_TYPE_TO_JOB_TYPE.get(task.task_type, "RESEARCH")
                payload = {
                    "task_id": task_id,
                    "task_uuid": task.task_uuid,
                    "task_type": task.task_type,
                    "required": bool(task.required),
                    "domain": task.domain,
                    "description": task.description,
                    "run_id": run_id,
                    "run_db_id": run_db_id,
                    "match_id": match_id,
                    "home_team_id": match_identity.home_team_id,
                    "away_team_id": match_identity.away_team_id,
                    "home_team": match_identity.home_team,
                    "away_team": match_identity.away_team,
                    "competition": match_identity.competition,
                    "scheduled_at": match_identity.scheduled_at.isoformat(),
                    "venue": match_identity.venue,
                    "data_cutoff_at": cutoff_iso,
                    "cutoff_datetime": cutoff_iso,
                    "cutoff": cutoff_iso,
                    "capabilities_required": task.capabilities_required,
                    "worker_capability": job_type,
                }
                job_id = str(uuid.uuid5(uuid.NAMESPACE_URL, "football-analysis:%s:%s" % (run_id, task.task_uuid)))
                fingerprint = self.queue.generate_fingerprint(job_type, match_id, payload, run_id)
                self.queue.store.create_job_on_connection(conn, job_id, job_type, match_id, run_id, payload, fingerprint, int(task.priority), 3)

                job_pk = conn.execute("SELECT id FROM jobs WHERE job_id=?", (job_id,)).fetchone()[0]
                task_uuid_to_job_id[task.task_uuid] = job_id
                task_uuid_to_job_pk[task.task_uuid] = int(job_pk)

                conn.execute("UPDATE research_tasks SET job_id=?,status='QUEUED',updated_at=CURRENT_TIMESTAMP WHERE id=?", (job_id, task_id))
                created.append(job_id)

            for task in tasks:
                if task.depends_on:
                    job_id = task_uuid_to_job_id[task.task_uuid]
                    job_pk = task_uuid_to_job_pk[task.task_uuid]
                    has_deps = False
                    for dep_uuid in task.depends_on:
                        parent_job_pk = task_uuid_to_job_pk.get(dep_uuid)
                        if parent_job_pk and parent_job_pk != job_pk:
                            conn.execute("INSERT OR IGNORE INTO job_dependencies(job_id, depends_on_job_id) VALUES(?, ?)", (job_pk, parent_job_pk))
                            has_deps = True

                    if has_deps:
                        conn.execute("UPDATE jobs SET status='BLOCKED' WHERE id=? AND status='PENDING'", (job_pk,))
                        conn.execute("UPDATE research_tasks SET status='BLOCKED' WHERE job_id=? AND status='QUEUED'", (job_id,))

            conn.commit()
        return created

    def start_pipeline(self, match_id: int, data_cutoff_at: Optional[datetime] = None) -> str:
        """Spustí pipeline pro existující zápas: Match Identity → Research Planner → Jobs."""
        match_identity = self._get_match_identity_from_id(match_id, data_cutoff_at=data_cutoff_at)
        if not match_identity:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            row = cursor.execute("SELECT status FROM matches WHERE id = ?", (match_id,)).fetchone()
            conn.close()
            if row:
                st = row[0] if row[0] else "NULL/EMPTY"
                raise ValueError(f"Match {match_id} exists but status is '{st}' (only explicit status RESOLVED is allowed). Pipeline cannot start.")
            raise ValueError(f"Match {match_id} does not exist")

        run_id = f"{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_M{match_id}_{uuid.uuid4().hex[:4]}"
        now_iso = datetime.now(timezone.utc).isoformat()
        max_cycles = self.config["orchestrator"]["audit_max_cycles"]
        cutoff_iso = match_identity.data_cutoff_at.isoformat() if match_identity.data_cutoff_at else None

        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO runs(run_id,status,started_at,pipeline_version,config_hash) VALUES(?,?,?,?,?)",
                (run_id, "RUNNING", now_iso, "part-11", None),
            )
            run_db_id = conn.execute(
                "SELECT id FROM runs WHERE run_id=?", (run_id,)
            ).fetchone()[0]
            conn.execute(
                "INSERT INTO pipeline_runs(run_id,match_id,state,cycle,max_cycles,data_cutoff_at,started_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                (run_id, match_id, MatchState.NEW, 1, max_cycles, cutoff_iso, now_iso, now_iso),
            )

        self.state_machine.transition_to(run_id, MatchState.DISCOVERY, "Match Identity resolved")

        tasks = self.planner.create_plan(match_identity)
        self._dispatch_research_tasks(tasks, match_id, run_id, match_identity)
        return run_id

    def start_pipeline_from_request(self, request: AnalysisRequest) -> str:
        """Vyhledá nebo založí zápas v DB a spustí pro něj kanonickou pipeline."""
        resolver = MatchResolver(db_path=self.db_path)
        match_identity = resolver.resolve_or_create(request)
        return self.start_pipeline(match_identity.match_id, data_cutoff_at=match_identity.data_cutoff_at)

    def tick(self, run_id: str):
        """Provede jeden deterministický krok pipeline a řídí joby pouze daného runu."""
        self.recovery.recover_dead_workers_and_jobs()
        self.scheduler.update_blocked_jobs()

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            run = conn.execute(
                "SELECT match_id, state, cycle, max_cycles, data_cutoff_at FROM pipeline_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            if not run:
                return

            match_id = run["match_id"]
            state = run["state"]
            cycle = int(run["cycle"])
            max_cycles = int(run["max_cycles"])

            raw_cutoff = run["data_cutoff_at"] if "data_cutoff_at" in run.keys() else None
            run_cutoff_dt = None
            if raw_cutoff:
                try:
                    run_cutoff_dt = parse_to_utc(raw_cutoff)
                except Exception:
                    run_cutoff_dt = None

            jobs = conn.execute(
                "SELECT id, job_type, status, result_json, payload_json "
                "FROM jobs WHERE match_id = ? AND run_id = ? ORDER BY id",
                (match_id, run_id),
            ).fetchall()

        terminal = {JobStatus.SUCCESS, JobStatus.FAILED, JobStatus.CANCELLED}

        if state == MatchState.DISCOVERY:
            research_jobs = [j for j in jobs if j["job_type"] in ("RESEARCH", "STATISTICS")]
            if research_jobs and all(j["status"] in terminal for j in research_jobs):
                if any(j["status"] == JobStatus.SUCCESS for j in research_jobs):
                    self.state_machine.transition_to(
                        run_id, MatchState.COLLECTING, "Research tasks complete"
                    )
                    self.state_machine.transition_to(
                        run_id, MatchState.NORMALIZING, "Research evidence collected"
                    )
                    self.state_machine.transition_to(
                        run_id, MatchState.CALCULATING, "Data normalized"
                    )
                else:
                    self.state_machine.transition_to(
                        run_id, MatchState.UNRESOLVED, "Research produced no usable result"
                    )
            return

        if state == MatchState.COLLECTING:
            research_jobs = [j for j in jobs if j["job_type"] in ("RESEARCH", "STATISTICS")]
            if research_jobs and all(j["status"] in terminal for j in research_jobs):
                if any(j["status"] == JobStatus.SUCCESS for j in research_jobs):
                    self.state_machine.transition_to(run_id, MatchState.NORMALIZING, "Research evidence collected")
                    self.state_machine.transition_to(run_id, MatchState.CALCULATING, "Data normalized")
                else:
                    self.state_machine.transition_to(run_id, MatchState.UNRESOLVED, "Research produced no usable result")
            return

        if state == MatchState.CALCULATING:
            statistics_jobs = [j for j in jobs if j["job_type"] == "STATISTICS"]
            if statistics_jobs and all(j["status"] in terminal for j in statistics_jobs):
                if any(j["status"] == JobStatus.SUCCESS for j in statistics_jobs):
                    match_ident = self._get_match_identity_from_id(match_id, data_cutoff_at=run_cutoff_dt)
                    self.state_machine.transition_to(run_id, MatchState.ANALYZING, "Statistics ready")
                    cutoff_str = match_ident.data_cutoff_at.isoformat() if match_ident and match_ident.data_cutoff_at else None
                    self.queue.create_job(
                        "AI_ANALYSIS",
                        match_id,
                        {
                            "phase": "analysis",
                            "run_id": run_id,
                            "match_id": match_id,
                            "run_db_id": self._get_run_db_id(run_id),
                            "db_path": self.db_path,
                            "data_cutoff_at": cutoff_str,
                            "match": {
                                "match_id": match_id,
                                "home_team": match_ident.home_team if match_ident else "",
                                "away_team": match_ident.away_team if match_ident else "",
                                "competition": match_ident.competition if match_ident else "",
                                "scheduled_at": match_ident.scheduled_at.isoformat() if match_ident else "",
                                "data_cutoff_at": cutoff_str,
                                "venue": match_ident.venue if match_ident else None,
                            } if match_ident else None,
                        },
                        priority=JobPriority.HIGH,
                        run_id=run_id,
                    )
                else:
                    self.state_machine.transition_to(run_id, MatchState.UNRESOLVED, "Statistics failed")
            return

        if state == MatchState.ANALYZING:
            ai_job = next(
                (j for j in jobs if j["job_type"] == "AI_ANALYSIS" and j["status"] == JobStatus.SUCCESS),
                None,
            )
            if ai_job:
                ai_res = json.loads(ai_job["result_json"]) if ai_job["result_json"] else {}
                match_ident = self._get_match_identity_from_id(match_id, data_cutoff_at=run_cutoff_dt)
                run_db_id = self._get_run_db_id(run_id)
                self.state_machine.transition_to(run_id, MatchState.AUDITING, "AI Analysis complete")
                cutoff_str = match_ident.data_cutoff_at.isoformat() if match_ident and match_ident.data_cutoff_at else None
                self.queue.create_job(
                    "AUDIT",
                    match_id,
                    {
                        "match_id": match_id,
                        "ai_analysis": ai_res,
                        "run_id": run_id,
                        "run_db_id": run_db_id,
                        "data_cutoff_at": cutoff_str,
                        "cycle": cycle,
                        "db_path": self.db_path,
                    },
                    priority=JobPriority.CRITICAL,
                    run_id=run_id,
                )
            return

        if state == MatchState.AUDITING:
            audit_job = next(
                (j for j in jobs if j["job_type"] == "AUDIT" and j["status"] == JobStatus.SUCCESS),
                None,
            )
            if not audit_job:
                return

            if not audit_job["result_json"]:
                self.state_machine.transition_to(run_id, MatchState.UNRESOLVED, "Audit job completed without result_json")
                return

            try:
                audit_res = json.loads(audit_job["result_json"])
            except Exception as e:
                self.state_machine.transition_to(run_id, MatchState.UNRESOLVED, f"Failed to parse audit result_json: {e}")
                return

            if not isinstance(audit_res, dict) or not audit_res:
                self.state_machine.transition_to(run_id, MatchState.UNRESOLVED, "Audit result_json is empty")
                return

            audit_status = audit_res.get("status")
            audit_score = audit_res.get("audit_score", 1.0)
            audit_issues = audit_res.get("issues", []) if isinstance(audit_res, dict) else []

            has_critical_cutoff = any(
                iss.get("type") in ("cutoff_missing", "cutoff_violation") and iss.get("severity") == "CRITICAL"
                for iss in audit_issues
            )

            if audit_status in {"AUDIT_COMPLETE", "PASS", "OK", "COMPLETED"}:
                if run_cutoff_dt is None:
                    self.state_machine.transition_to(run_id, MatchState.UNRESOLVED, "Pipeline cannot complete because per-run data_cutoff_at is missing or invalid")
                elif has_critical_cutoff:
                    self.state_machine.transition_to(run_id, MatchState.UNRESOLVED, "Audit contains critical cutoff issue")
                elif audit_score is not None and float(audit_score) < 0.3:
                    self.state_machine.transition_to(run_id, MatchState.UNRESOLVED, f"Audit score too low ({audit_score})")
                else:
                    readiness = self.coverage_engine.evaluate_run(run_id, self._get_run_db_id(run_id))
                    if not readiness.ready:
                        reasons = ", ".join(readiness.blocking_reasons)
                        if cycle < max_cycles:
                            self.state_machine.transition_to(run_id, MatchState.RESEARCHING, f"Coverage check failed ({reasons}) - cycle {cycle}")
                            match_ident = self._get_match_identity_from_id(match_id, data_cutoff_at=run_cutoff_dt)
                            if match_ident:
                                task_reqs = [
                                    TaskRequirement(
                                        task_uuid=f"REPAIR-COVERAGE-{run_id}-{cycle}-{uuid.uuid4().hex[:6]}",
                                        domain="GENERAL",
                                        task_type="FACT_COLLECTION",
                                        description=f"Repair research for missing coverage: {reasons}",
                                        priority=80,
                                        required=True,
                                        capabilities_required=["RESEARCH"],
                                    )
                                ]
                                self._dispatch_research_tasks(task_reqs, match_id, run_id, match_ident)
                        else:
                            self.state_machine.transition_to(run_id, MatchState.UNRESOLVED, f"Coverage check failed and max cycles reached: {reasons}")
                    else:
                        self.state_machine.transition_to(run_id, MatchState.FINALIZING, "Audit and coverage check passed")
                        if self._are_all_jobs_completed(run_id):
                            self.state_machine.transition_to(run_id, MatchState.COMPLETED, "Pipeline successful")
            elif audit_status == "RESEARCH_REQUIRED":
                if cycle < max_cycles:
                    self.state_machine.transition_to(run_id, MatchState.RESEARCHING, f"Research required - cycle {cycle}")
                    required_research = audit_res.get("required_research") or audit_res.get("research_jobs") or []
                    if not required_research:
                        required_research = [{"domain": "GENERAL", "reason": "audit_required"}]

                    match_ident = self._get_match_identity_from_id(match_id, data_cutoff_at=run_cutoff_dt)
                    if match_ident:
                        task_reqs = []
                        for item in required_research:
                            domain = str(item.get("domain") or "GENERAL")
                            task_type = str(item.get("job_type") or "FACT_COLLECTION")
                            if task_type not in ("FACT_COLLECTION", "STAT_COLLECTION", "NEWS_COLLECTION"):
                                task_type = "FACT_COLLECTION"
                            desc = str(item.get("description") or item.get("reason") or f"Audit repair for {domain}")
                            prio = int(item.get("priority", 80))
                            task_uuid = f"REPAIR-{run_id}-{cycle}-{uuid.uuid4().hex[:6]}"
                            task_reqs.append(TaskRequirement(
                                task_uuid=task_uuid,
                                domain=domain,
                                task_type=task_type,
                                description=desc,
                                priority=prio,
                                required=True,
                                capabilities_required=["RESEARCH"],
                            ))
                        self._dispatch_research_tasks(task_reqs, match_id, run_id, match_ident)
                    else:
                        for item in required_research:
                            self.queue.create_job(
                                "RESEARCH",
                                match_id,
                                {**item, "run_id": run_id, "cycle": cycle},
                                priority=JobPriority.HIGH,
                                run_id=run_id,
                            )
                else:
                    self.state_machine.transition_to(run_id, MatchState.UNRESOLVED, f"Max cycles ({max_cycles}) reached")
            else:
                self.state_machine.transition_to(run_id, MatchState.UNRESOLVED, f"Audit finished with status: {audit_status}")
            return

        if state == MatchState.RESEARCHING:
            research_jobs = [
                j for j in jobs
                if j["job_type"] == "RESEARCH"
                and j["status"] in terminal
            ]
            if research_jobs:
                self.state_machine.transition_to(run_id, MatchState.REANALYZING, "Research data collected")
                with sqlite3.connect(self.db_path) as conn:
                    conn.execute(
                        "UPDATE pipeline_runs SET cycle = cycle + 1, updated_at = ? WHERE run_id = ?",
                        (datetime.now(timezone.utc).isoformat(), run_id),
                    )
                    conn.commit()
                self.queue.create_job(
                    "AI_ANALYSIS",
                    match_id,
                    {
                        "phase": "re_analysis",
                        "run_id": run_id,
                        "match_id": match_id,
                        "run_db_id": self._get_run_db_id(run_id),
                        "cycle": cycle + 1,
                    },
                    priority=JobPriority.HIGH,
                    run_id=run_id,
                )
                self.state_machine.transition_to(run_id, MatchState.ANALYZING, "Re-running AI Analysis")
            return

        if state == MatchState.FINALIZING and self._are_all_jobs_completed(run_id):
            if run_cutoff_dt is None:
                self.state_machine.transition_to(run_id, MatchState.UNRESOLVED, "Finalizing failed because per-run data_cutoff_at is missing or invalid")
            elif not self._are_all_required_jobs_successful(run_id):
                self.state_machine.transition_to(run_id, MatchState.UNRESOLVED, "Finalizing failed because required jobs were failed or cancelled")
            else:
                readiness = self.coverage_engine.evaluate_run(run_id, self._get_run_db_id(run_id))
                if readiness.ready:
                    self.state_machine.transition_to(run_id, MatchState.COMPLETED, "All jobs completed and coverage passed")
                else:
                    self.state_machine.transition_to(run_id, MatchState.UNRESOLVED, f"Finalizing failed coverage check: {', '.join(readiness.blocking_reasons)}")

    def _get_run_db_id(self, run_id: str) -> int:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute("SELECT id FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        if not row:
            raise KeyError(run_id)
        return int(row[0])

    def _are_all_jobs_completed(self, run_id: str) -> bool:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            "SELECT status FROM jobs WHERE run_id = ?",
            (run_id,),
        )
        rows = cursor.fetchall()
        conn.close()
        if not rows:
            return False
        terminal = {JobStatus.SUCCESS, JobStatus.FAILED, JobStatus.CANCELLED}
        return all(row["status"] in terminal for row in rows)

    def _are_all_required_jobs_successful(self, run_id: str) -> bool:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, status, payload_json FROM jobs WHERE run_id = ?",
            (run_id,),
        )
        rows = cursor.fetchall()
        conn.close()
        if not rows:
            return False

        for row in rows:
            status = row["status"]
            payload = {}
            if row["payload_json"]:
                try:
                    payload = json.loads(row["payload_json"])
                except Exception:
                    pass

            is_required = payload.get("required", True)
            if is_required and status != JobStatus.SUCCESS:
                return False
        return True


class MatchOrchestrator:
    """
    Fasáda delegující na MasterOrchestrator.
    Přijme AnalysisRequest, vyřeší identitu zápasu přes MatchResolver,
    a spustí kanonickou pipeline přes MasterOrchestrator.
    """

    def __init__(self, db_path: str = "database/football.db", config_path: str = "config/pipeline.yaml"):
        self.db_path = db_path
        self.resolver = MatchResolver(db_path=db_path)
        self.master = MasterOrchestrator(db_path=db_path, config_path=config_path)

    def start_analysis_run(self, request: AnalysisRequest) -> Dict[str, Any]:
        """
        Spustí nový analytický běh delegací na MasterOrchestrator.
        """
        match_identity = self.resolver.resolve_or_create(request)
        run_id = self.master.start_pipeline(match_identity.match_id, data_cutoff_at=match_identity.data_cutoff_at)

        with sqlite3.connect(self.db_path) as conn:
            tasks_count = conn.execute("SELECT COUNT(*) FROM research_tasks WHERE run_id=?", (run_id,)).fetchone()[0]
            jobs_count = conn.execute("SELECT COUNT(*) FROM jobs WHERE run_id=?", (run_id,)).fetchone()[0]

        return {
            "run_id": run_id,
            "match_id": match_identity.match_id,
            "status": "DISCOVERY",
            "tasks_count": tasks_count,
            "jobs_created": jobs_count,
        }
