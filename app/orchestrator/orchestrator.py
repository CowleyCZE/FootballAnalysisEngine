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
from app.orchestrator.match_resolver import MatchResolver, MatchNotFoundException, AmbiguousMatchException
from app.orchestrator.research_planner import ResearchPlanner
from app.orchestrator.models import AnalysisRequest, MatchIdentity, TaskRequirement
from app.jobs.queue import JobQueue
from app.jobs.models import JobStatus, JobPriority
from app.database.connection import init_database_schema

logger = logging.getLogger(__name__)

# Mapování typu tasku (z ResearchPlaneru) na typ jobu ve frontě
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
        init_database_schema(db_path)

    def _get_match_identity_from_id(self, match_id: int) -> Optional[MatchIdentity]:
        """Načte MatchIdentity z databáze na základě match_id."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        try:
            cursor.execute("""
                SELECT m.id as match_id, m.home_team_id, m.away_team_id,
                       COALESCE(m.competition_id, 0) as competition_id, m.scheduled_at
                FROM matches m
                WHERE m.id = ?
            """, (match_id,))
            row = cursor.fetchone()
            if not row:
                return None
            scheduled_str = row["scheduled_at"]
            scheduled_dt = datetime.fromisoformat(scheduled_str) if scheduled_str else datetime.now(timezone.utc)
            return MatchIdentity(
                match_id=row["match_id"],
                home_team_id=row["home_team_id"],
                away_team_id=row["away_team_id"],
                competition_id=row["competition_id"],
                scheduled_at=scheduled_dt,
                data_cutoff_at=scheduled_dt,
            )
        finally:
            conn.close()

    def _dispatch_research_tasks(self, tasks: List[TaskRequirement], match_id: int, run_id: str) -> List[str]:
        """
        Vytvoří joby ve frontě pro každý TaskRequirement z ResearchPlaneru.
        Vrátí seznam vytvořených job_id.
        """
        created = []
        for task in tasks:
            job_type = _TASK_TYPE_TO_JOB_TYPE.get(task.task_type, "RESEARCH")
            payload = {
                "task_uuid": task.task_uuid,
                "domain": task.domain,
                "description": task.description,
                "run_id": run_id,
            }
            job_id = self.queue.create_job(
                job_type=job_type,
                match_id=match_id,
                payload=payload,
                priority=task.priority,
                run_id=run_id,
            )
            if job_id:
                created.append(job_id)
                logger.info(f"[ORCHESTRATOR] Vytvořen job {job_id} ({job_type}) pro doménu {task.domain}")
        return created

    def start_pipeline(self, match_id: int) -> str:
        """Spustí pipeline pro existující zápas: Match Identity → Research Planner → Jobs."""
        match_identity = self._get_match_identity_from_id(match_id)
        if not match_identity:
            raise ValueError(f"Match {match_id} does not exist")

        run_id = f"{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_M{match_id}_{uuid.uuid4().hex[:4]}"
        now_iso = datetime.now(timezone.utc).isoformat()
        max_cycles = self.config["orchestrator"]["audit_max_cycles"]

        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO runs(run_id,status,started_at,pipeline_version,config_hash) VALUES(?,?,?,?,?)",
                (run_id, "RUNNING", now_iso, "part-11", None),
            )
            run_db_id = conn.execute("SELECT id FROM runs WHERE run_id=?", (run_id,)).fetchone()[0]
            conn.execute(
                "INSERT INTO pipeline_runs(run_id,match_id,state,cycle,max_cycles,started_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                (run_id, match_id, MatchState.NEW, 1, max_cycles, now_iso, now_iso),
            )

        self.state_machine.transition_to(run_id, MatchState.DISCOVERY, "Match Identity resolved")

        tasks = self.planner.create_plan(match_identity)
        created = []
        for task in tasks:
            payload = {
                "task_uuid": task.task_uuid,
                "domain": task.domain,
                "description": task.description,
                "run_id": run_id,
                "run_db_id": run_db_id,
                "capabilities_required": task.capabilities_required,
                "cutoff": match_identity.data_cutoff_at.isoformat(),
            }
            job_type = _TASK_TYPE_TO_JOB_TYPE.get(task.task_type, "RESEARCH")
            job_id = self.queue.create_job(
                job_type=job_type,
                match_id=match_id,
                payload=payload,
                priority=task.priority,
                run_id=run_id,
            )
            if job_id:
                created.append(job_id)

        return run_id

    def tick(self, run_id: str):
        """Provede jeden tik stavového automatu pro daný run."""
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
            "SELECT id, job_type, status, result_json FROM jobs WHERE match_id = ? AND run_id = ?",
            (match_id, run_id),
        )
        jobs = cursor.fetchall()
        conn.close()

        if state == MatchState.DISCOVERY:
            # Po dokončení RESEARCH a STATISTICS jobů přejdeme do COLLECTING
            research_jobs = [j for j in jobs if j["job_type"] in ("RESEARCH", "STATISTICS")]
            if research_jobs and all(j["status"] in (JobStatus.SUCCESS, JobStatus.FAILED) for j in research_jobs):
                self.state_machine.transition_to(run_id, MatchState.COLLECTING, "Research tasks complete")
                self.queue.create_job("CRAWL", match_id, {"phase": "evidence_crawl", "run_id": run_id}, priority=JobPriority.HIGH, run_id=run_id)

        elif state == MatchState.COLLECTING:
            if any(j["job_type"] == "CRAWL" and j["status"] == JobStatus.SUCCESS for j in jobs):
                self.state_machine.transition_to(run_id, MatchState.NORMALIZING, "Crawling complete")
                self.state_machine.transition_to(run_id, MatchState.CALCULATING, "Data normalized")

        elif state == MatchState.CALCULATING:
            if any(j["job_type"] == "STATISTICS" and j["status"] == JobStatus.SUCCESS for j in jobs):
                self.state_machine.transition_to(run_id, MatchState.ANALYZING, "Statistics ready")
                self.queue.create_job("AI_ANALYSIS", match_id, {"phase": "analysis", "run_id": run_id}, priority=JobPriority.HIGH, run_id=run_id)

        elif state == MatchState.ANALYZING:
            ai_job = next((j for j in jobs if j["job_type"] == "AI_ANALYSIS" and j["status"] == JobStatus.SUCCESS), None)
            if ai_job:
                self.state_machine.transition_to(run_id, MatchState.AUDITING, "AI Analysis complete")
                ai_res = json.loads(ai_job["result_json"]) if ai_job["result_json"] else {}
                self.queue.create_job("AUDIT", match_id, {
                    "match_id": match_id,
                    "ai_analysis": ai_res,
                    "run_id": run_id,
                    "cycle": cycle,
                    "db_path": self.db_path,
                }, priority=JobPriority.CRITICAL, run_id=run_id)

        elif state == MatchState.AUDITING:
            audit_job = next((j for j in jobs if j["job_type"] == "AUDIT" and j["status"] == JobStatus.SUCCESS), None)
            if audit_job:
                audit_res = json.loads(audit_job["result_json"]) if audit_job["result_json"] else {}
                audit_status = audit_res.get("status")

                if audit_status == "AUDIT_COMPLETE":
                    self.state_machine.transition_to(run_id, MatchState.FINALIZING, "Audit passed")
                    self.state_machine.transition_to(run_id, MatchState.COMPLETED, "Pipeline successful")
                elif audit_status == "RESEARCH_REQUIRED":
                    if cycle < max_cycles:
                        self.state_machine.transition_to(run_id, MatchState.RESEARCHING, f"Research required — cycle {cycle}")
                        research_tasks_payload = audit_res.get("required_research", [{"domain": "GENERAL", "reason": "audit_required"}])
                        for rt in research_tasks_payload:
                            self.queue.create_job(
                                "RESEARCH",
                                match_id,
                                {**rt, "run_id": run_id, "cycle": cycle},
                                priority=JobPriority.HIGH,
                                run_id=run_id,
                            )
                    else:
                        self.state_machine.transition_to(run_id, MatchState.UNRESOLVED, f"Max cycles ({max_cycles}) reached")
                else:
                    # Audit selhání nebo neznámý stav → UNRESOLVED
                    self.state_machine.transition_to(run_id, MatchState.UNRESOLVED, f"Audit finished with status: {audit_status}")

        elif state == MatchState.RESEARCHING:
            research_jobs = [j for j in jobs if j["job_type"] == "RESEARCH" and j["status"] == JobStatus.SUCCESS]
            if research_jobs:
                conn2 = sqlite3.connect(self.db_path)
                conn2.execute("UPDATE pipeline_runs SET cycle = cycle + 1 WHERE run_id = ?", (run_id,))
                conn2.commit()
                conn2.close()
                self.state_machine.transition_to(run_id, MatchState.REANALYZING, "Research data collected")
                self.queue.create_job("AI_ANALYSIS", match_id, {"phase": "re_analysis", "run_id": run_id, "cycle": cycle + 1}, priority=JobPriority.HIGH, run_id=run_id)
                self.state_machine.transition_to(run_id, MatchState.ANALYZING, "Re-running AI Analysis")

        elif state == MatchState.FINALIZING:
            if self._are_all_jobs_completed(run_id):
                self.state_machine.transition_to(run_id, MatchState.COMPLETED, "All jobs completed")

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


class MatchOrchestrator:
    """
    Fasáda pro spuštění analýzy na základě AnalysisRequest.
    Přijme AnalysisRequest, vyřeší identitu zápasu přes MatchResolver,
    pak deleguje na MasterOrchestrator.

    Tok: AnalysisRequest → MatchResolver → MatchIdentity → ResearchPlanner → Jobs
    """

    def __init__(self, db_path: str = "database/football.db", config_path: str = "config/pipeline.yaml"):
        self.db_path = db_path
        self.resolver = MatchResolver(db_path=db_path)
        self.planner = ResearchPlanner()
        self.queue = JobQueue(db_path=db_path)
        self.state_machine = MatchStateMachine(db_path=db_path)
        try:
            self.config = PipelineConfig.load(config_path)
        except Exception:
            self.config = {"orchestrator": {"audit_max_cycles": 3, "worker_timeout": 120}}
        init_database_schema(db_path)

    def start_analysis_run(self, request: AnalysisRequest) -> Dict[str, Any]:
        """
        Spustí nový analytický běh.
        1. Resolves match identity from DB
        2. Creates pipeline_run record
        3. Calls ResearchPlanner to get task list
        4. Dispatches tasks as jobs into queue

        Raises:
            MatchNotFoundException: pokud zápas není v DB
            AmbiguousMatchException: pokud bylo nalezeno více kandidátů
        """
        # Krok 1: Resolve identity (může vyhodit MatchNotFoundException / AmbiguousMatchException)
        match_identity = self.resolver.resolve(request)

        run_id = f"{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_M{match_identity.match_id}_{uuid.uuid4().hex[:4]}"
        now_iso = datetime.now(timezone.utc).isoformat()
        max_cycles = self.config["orchestrator"].get("audit_max_cycles", 3)

        # Krok 2: Zápis canonical run + pipeline_run
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO runs (run_id, status, started_at, pipeline_version) VALUES (?, ?, ?, ?)",
            (run_id, "RUNNING", now_iso, "part-11"),
        )
        cursor.execute(
            "INSERT INTO pipeline_runs (run_id, match_id, state, cycle, max_cycles, started_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (run_id, match_identity.match_id, MatchState.NEW, 1, max_cycles, now_iso, now_iso)
        )
        conn.commit()
        conn.close()

        # Přechod do stavu DISCOVERY
        self.state_machine.transition_to(run_id, MatchState.DISCOVERY, "Match resolved — creating research plan")

        # Krok 3: ResearchPlanner vytvoří seznam tasků
        tasks = self.planner.create_plan(match_identity)
        logger.info(f"[MatchOrchestrator] ResearchPlanner vytvořil {len(tasks)} tasků pro {request.home_team} vs {request.away_team}")

        # Krok 4: Dispatch tasků jako joby
        created_jobs = []
        for task in tasks:
            job_type = _TASK_TYPE_TO_JOB_TYPE.get(task.task_type, "RESEARCH")
            payload = {
                "task_uuid": task.task_uuid,
                "domain": task.domain,
                "description": task.description,
                "run_id": run_id,
                "cutoff": match_identity.data_cutoff_at.isoformat(),
            }
            job_id = self.queue.create_job(
                job_type=job_type,
                match_id=match_identity.match_id,
                payload=payload,
                priority=task.priority,
                run_id=run_id,
            )
            if job_id:
                created_jobs.append(job_id)

        # Přechod do stavu RESEARCHING (joby jsou vytvořeny a čekají na workery)
        self.state_machine.transition_to(run_id, MatchState.RESEARCHING, f"Research plan dispatched: {len(created_jobs)} jobs")

        return {
            "run_id": run_id,
            "match_id": match_identity.match_id,
            "status": "RESEARCHING",
            "tasks_count": len(tasks),
            "jobs_created": len(created_jobs),
        }
