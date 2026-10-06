from datetime import datetime, timezone
import json
import sqlite3
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from app.orchestrator.orchestrator import MasterOrchestrator, MatchOrchestrator
from app.orchestrator.models import AnalysisRequest
from app.orchestrator.match_resolver import MatchNotFoundException, AmbiguousMatchException
from app.jobs.queue import JobQueue


app = FastAPI(
    title="Football Analysis Engine",
    version="0.2.0",
)


DB_PATH = "database/football.db"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class AnalysisStartRequest(BaseModel):
    match_id: Optional[int] = None
    home_team: Optional[str] = None
    away_team: Optional[str] = None
    competition: Optional[str] = None
    scheduled_at: Optional[str] = None
    timezone: str = "Europe/Prague"
    priority: int = 50


class WorkerRegistration(BaseModel):
    worker_id: str
    worker_name: str = "worker"
    worker_version: str = "1.0.0"
    capabilities: List[str] = Field(default_factory=list)


class WorkerHeartbeat(BaseModel):
    worker_id: str
    status: str = "online"


class JobClaimRequest(BaseModel):
    worker_id: str
    capabilities: List[str] = Field(default_factory=lambda: ["generic"])


class JobResult(BaseModel):
    worker_id: str
    status: str
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


@app.get("/")
def root():
    return {
        "system": "Football Analysis Engine",
        "status": "online",
        "version": "0.2.0",
    }


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "timestamp": now(),
    }


@app.get("/api/worker/heartbeat")
def notebook_worker_heartbeat():
    return {
        "status": "online",
        "worker": "notebook",
        "timestamp": now(),
    }


@app.post("/api/analysis/start")
def start_analysis(req: AnalysisStartRequest):
    if req.match_id is not None:
        master = MasterOrchestrator(db_path=DB_PATH)
        try:
            run_id = master.start_pipeline(req.match_id)
            return {
                "status": "started",
                "run_id": run_id,
                "match_id": req.match_id,
            }
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))

    if req.home_team and req.away_team and req.scheduled_at:
        try:
            scheduled_dt = datetime.fromisoformat(req.scheduled_at)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid scheduled_at ISO timestamp")

        analysis_req = AnalysisRequest(
            home_team=req.home_team,
            away_team=req.away_team,
            competition=req.competition or "",
            scheduled_at=scheduled_dt,
            timezone=req.timezone,
            priority=req.priority,
        )
        orchestrator = MatchOrchestrator(db_path=DB_PATH)
        try:
            result = orchestrator.start_analysis_run(analysis_req)
            return result
        except MatchNotFoundException as e:
            raise HTTPException(status_code=404, detail=str(e))
        except AmbiguousMatchException as e:
            raise HTTPException(status_code=400, detail=str(e))

    raise HTTPException(status_code=400, detail="Must provide either match_id or (home_team, away_team, scheduled_at)")


@app.get("/api/analysis/{run_id}")
def get_analysis_status(run_id: str):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        run = conn.execute("SELECT * FROM pipeline_runs WHERE run_id = ?", (run_id,)).fetchone()
        if not run:
            run_base = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
            if not run_base:
                raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
            return {
                "run_id": run_id,
                "status": run_base["status"],
                "started_at": run_base["started_at"],
                "finished_at": run_base["finished_at"],
            }

        jobs = conn.execute("SELECT job_id, job_type, status, attempts, error_text, created_at, finished_at FROM jobs WHERE run_id = ?", (run_id,)).fetchall()
        jobs_list = [dict(j) for j in jobs]

        return {
            "run_id": run_id,
            "match_id": run["match_id"],
            "state": run["state"],
            "cycle": run["cycle"],
            "max_cycles": run["max_cycles"],
            "started_at": run["started_at"],
            "updated_at": run["updated_at"],
            "finished_at": run["finished_at"],
            "jobs_count": len(jobs_list),
            "jobs": jobs_list,
        }
    finally:
        conn.close()


@app.post("/api/workers/register")
def register_worker(worker: WorkerRegistration):
    queue = JobQueue(db_path=DB_PATH)
    queue.store.register_worker(worker.worker_id, worker.capabilities, worker_type=worker.worker_name)
    return {
        "status": "registered",
        "worker_id": worker.worker_id,
    }


@app.post("/api/workers/heartbeat")
def worker_heartbeat(data: WorkerHeartbeat):
    queue = JobQueue(db_path=DB_PATH)
    queue.store.heartbeat(data.worker_id)
    return {
        "status": "ok",
        "worker_id": data.worker_id,
        "timestamp": now(),
    }


@app.post("/api/jobs/claim")
def claim_job(data: JobClaimRequest):
    queue = JobQueue(db_path=DB_PATH)
    job = queue.claim_job(data.worker_id, data.capabilities)
    if not job:
        return {"status": "no_job"}

    return {
        "status": "job_assigned",
        "job": {
            "id": job["job_id"],
            "job_type": job["job_type"],
            "payload": job["payload"],
        }
    }


@app.post("/api/jobs/{job_id}/result")
def job_result(job_id: str, data: JobResult):
    queue = JobQueue(db_path=DB_PATH)
    status_mapped = data.status.upper()
    if status_mapped == "SUCCESS":
        queue.update_job_status(job_id, "SUCCESS", result=data.result, worker_id=data.worker_id)
    else:
        queue.update_job_status(job_id, "FAILED", error=data.error, worker_id=data.worker_id)

    return {"status": "ok", "job_id": job_id}
