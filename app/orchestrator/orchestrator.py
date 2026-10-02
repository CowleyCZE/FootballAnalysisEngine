import sqlite3
import uuid
from datetime import datetime
from typing import Dict, Any

from app.orchestrator.models import AnalysisRequest, ResearchReadiness
from app.orchestrator.match_resolver import MatchResolver
from app.orchestrator.research_planner import ResearchPlanner
from app.orchestrator.task_dispatcher import TaskDispatcher
from app.orchestrator.coverage import CoverageEngine
from app.orchestrator.state_machine import RunStatus, TaskStatus

class MatchOrchestrator:
    def __init__(self, db_path: str = "database/football.db"):
        self.db_path = db_path
        self.resolver = MatchResolver(db_path)
        self.planner = ResearchPlanner()
        self.dispatcher = TaskDispatcher()
        self.coverage_engine = CoverageEngine(db_path)

    def init_db_tables(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS analysis_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_uuid TEXT NOT NULL UNIQUE,
                match_id INTEGER,
                status TEXT NOT NULL,
                priority INTEGER NOT NULL DEFAULT 50,
                data_cutoff_at TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                started_at TEXT,
                completed_at TEXT,
                error_message TEXT,
                FOREIGN KEY (match_id) REFERENCES matches(id)
            );
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS research_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_uuid TEXT NOT NULL UNIQUE,
                run_id INTEGER NOT NULL,
                domain TEXT NOT NULL,
                task_type TEXT NOT NULL,
                description TEXT NOT NULL,
                priority INTEGER NOT NULL DEFAULT 50,
                required INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'PENDING',
                assigned_worker TEXT,
                retry_count INTEGER NOT NULL DEFAULT 0,
                max_retries INTEGER NOT NULL DEFAULT 3,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                started_at TEXT,
                completed_at TEXT,
                error_message TEXT,
                FOREIGN KEY (run_id) REFERENCES analysis_runs(id)
            );
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS research_conflicts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL,
                domain TEXT NOT NULL,
                description TEXT NOT NULL,
                severity TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'OPEN',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                resolved_at TEXT,
                FOREIGN KEY (run_id) REFERENCES analysis_runs(id)
            );
        """)
        
        conn.commit()
        conn.close()

    def start_analysis_run(self, request: AnalysisRequest) -> Dict[str, Any]:
        self.init_db_tables()
        run_uuid = f"RUN-{uuid.uuid4().hex[:8].upper()}"
        
        # 1. Resolve match
        match_identity = self.resolver.resolve(request)
        
        # 2. Uložení runu do DB
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO analysis_runs (run_uuid, match_id, status, priority, data_cutoff_at)
            VALUES (?, ?, ?, ?, ?)
        """, (run_uuid, match_identity.match_id, RunStatus.PLANNING, request.priority, match_identity.data_cutoff_at.isoformat()))
        
        run_id = cursor.lastrowid

        # 3. Vytvoření plánu a úkolů
        tasks = self.planner.create_plan(match_identity)
        
        for task in tasks:
            assigned = self.dispatcher.select_worker(task.capabilities_required)
            cursor.execute("""
                INSERT INTO research_tasks (task_uuid, run_id, domain, task_type, description, priority, required, status, assigned_worker)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                task.task_uuid, run_id, task.domain, task.task_type, task.description,
                task.priority, 1 if task.required else 0, TaskStatus.QUEUED, assigned
            ))

        # Posun stavu do RESEARCHING
        cursor.execute("UPDATE analysis_runs SET status = ? WHERE id = ?", (RunStatus.RESEARCHING, run_id))
        conn.commit()
        conn.close()

        return {
            "run_id": run_id,
            "run_uuid": run_uuid,
            "match_id": match_identity.match_id,
            "status": RunStatus.RESEARCHING,
            "tasks_count": len(tasks)
        }

    def check_readiness(self, run_id: int) -> ResearchReadiness:
        return self.coverage_engine.evaluate_run(run_id)