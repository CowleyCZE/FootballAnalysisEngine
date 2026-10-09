import asyncio
from datetime import datetime, timezone
import json
import os
import sqlite3
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, HTTPException, Header, Depends, status
from pydantic import BaseModel, Field

from app.orchestrator.orchestrator import MasterOrchestrator, MatchOrchestrator
from app.orchestrator.models import AnalysisRequest
from app.orchestrator.match_resolver import MatchNotFoundException, AmbiguousMatchException, UnverifiedMatchException
from app.search.engine import SearchEngine
from app.search.models import QuerySpec
from app.search.searxng_client import SearXNGClient
from app.jobs.queue import JobQueue


app = FastAPI(
    title="Football Analysis Engine",
    version="0.2.0",
)


DB_PATH = "database/football.db"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def verify_api_auth(
    x_worker_token: Optional[str] = Header(None, alias="X-Worker-Token"),
    authorization: Optional[str] = Header(None, alias="Authorization"),
):
    expected_token = os.getenv("WORKER_API_TOKEN") or os.getenv("API_SECRET_TOKEN")
    if not expected_token:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="API token authentication is not configured on the server. Access blocked for security.",
        )

    provided_token = x_worker_token
    if not provided_token and authorization and authorization.lower().startswith("bearer "):
        provided_token = authorization[7:].strip()

    if provided_token != expected_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing worker API token",
        )
    return True


class AnalysisStartRequest(BaseModel):
    match_id: Optional[int] = None
    home_team: Optional[str] = None
    away_team: Optional[str] = None
    competition: Optional[str] = None
    scheduled_at: Optional[str] = None
    timezone: str = "Europe/Prague"
    priority: int = 50


class SearchInternalRequest(BaseModel):
    query: str
    language: str = "en"
    priority: int = 50
    time_range: Optional[str] = None
    reason: str = ""
    team: str = ""
    topic_terms: List[str] = Field(default_factory=list)
    data_cutoff_at: Optional[str] = None


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
    result: Optional[Any] = None
    result_json: Optional[Any] = None
    error: Optional[str] = None


@app.get("/")
def root():
    return {
        "system": "Football Analysis Engine",
        "status": "online",
        "version": "0.2.0",
    }


@app.get("/health")
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


@app.post("/api/internal/search", dependencies=[Depends(verify_api_auth)])
def internal_search(req: SearchInternalRequest):
    """Interní vyhledávací proxy endpoint pro odlehčené Note 9 workery."""
    client = SearXNGClient(
        base_url=os.getenv("SEARXNG_URL", "http://127.0.0.1:8080"),
        timeout=float(os.getenv("SEARXNG_TIMEOUT", "30")),
    )
    engine = SearchEngine(client=client)
    spec = QuerySpec(
        query=req.query,
        language=req.language,
        priority=req.priority,
        time_range=req.time_range,
        reason=req.reason,
    )
    cutoff = datetime.fromisoformat(req.data_cutoff_at.replace("Z", "+00:00")) if req.data_cutoff_at else None
    results = asyncio.run(
        engine.search(
            query=spec,
            team=req.team,
            topic_terms=req.topic_terms,
            data_cutoff_at=cutoff,
        )
    )
    serialized = [
        {
            "title": r.title,
            "url": r.url,
            "snippet": r.content,
            "content": r.content,
            "engine": r.engine,
            "publishedDate": r.published_at,
            "published_at": r.published_at,
            "score": r.score,
            "relevance": r.relevance,
            "source_type": r.source_type,
            "retrieved_at": r.retrieved_at,
        }
        for r in results
    ]
    return {
        "status": "COMPLETED",
        "query": req.query,
        "results": serialized,
        "result_count": len(serialized),
        "source": "notebook_proxy",
    }


@app.post("/api/analysis/start", dependencies=[Depends(verify_api_auth)])
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
        except UnverifiedMatchException as e:
            raise HTTPException(status_code=404, detail=str(e))
        except AmbiguousMatchException as e:
            raise HTTPException(status_code=400, detail=str(e))

    raise HTTPException(status_code=400, detail="Must provide either match_id or (home_team, away_team, scheduled_at)")


@app.get("/api/analysis/{run_id}", dependencies=[Depends(verify_api_auth)])
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


@app.get("/api/analysis/{run_id}/result", dependencies=[Depends(verify_api_auth)])
def get_analysis_result(run_id: str, include_historical: bool = False):
    """Vrátí finální analytický výsledek s kompletní dohledatelností (claims, evidence, cutoff, audit).

    Standardně filtruje výhradně podle c.run_id = ?. Pokud je include_historical=True, přimíchává i
    historické claims ze stejného match_id označené s příznakem archived=True.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        run = conn.execute("SELECT * FROM pipeline_runs WHERE run_id = ?", (run_id,)).fetchone()
        if not run:
            raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

        match_id = run["match_id"]
        run_base = conn.execute("SELECT id FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        run_db_id = run_base["id"] if run_base else None

        cutoff_row = conn.execute("SELECT data_cutoff_at FROM research_tasks WHERE run_id = ? AND data_cutoff_at IS NOT NULL LIMIT 1", (run_id,)).fetchone()
        if not cutoff_row:
            cutoff_row = conn.execute("SELECT scheduled_at as data_cutoff_at FROM matches WHERE id = ?", (match_id,)).fetchone()
        data_cutoff_at = cutoff_row["data_cutoff_at"] if cutoff_row else None

        claims = []
        if run_db_id:
            if include_historical:
                claim_rows = conn.execute("""
                    SELECT c.id, c.run_id, c.claim_text, c.claim_type, c.normalized_claim, c.status, c.confidence, c.valid_from
                    FROM claims c
                    WHERE c.run_id = ? OR c.match_id = ?
                """, (run_db_id, match_id)).fetchall()
            else:
                claim_rows = conn.execute("""
                    SELECT c.id, c.run_id, c.claim_text, c.claim_type, c.normalized_claim, c.status, c.confidence, c.valid_from
                    FROM claims c
                    WHERE c.run_id = ?
                """, (run_db_id,)).fetchall()

            for cr in claim_rows:
                ev_rows = conn.execute("""
                    SELECT e.quoted_text, e.extracted_value, d.url as source_url, d.published_at, d.canonical_url
                    FROM claim_evidence ce
                    JOIN evidence e ON e.id = ce.evidence_id
                    JOIN documents d ON d.id = e.document_id
                    WHERE ce.claim_id = ?
                """, (cr["id"],)).fetchall()
                is_archived = (cr["run_id"] != run_db_id)
                claims.append({
                    "claim_id": cr["id"],
                    "claim_text": cr["claim_text"],
                    "claim_type": cr["claim_type"],
                    "normalized_claim": cr["normalized_claim"],
                    "status": cr["status"],
                    "confidence": cr["confidence"],
                    "valid_from": cr["valid_from"],
                    "archived": is_archived,
                    "evidence": [dict(ev) for ev in ev_rows],
                })

        ai_job = conn.execute("SELECT result_json FROM jobs WHERE run_id = ? AND job_type = 'AI_ANALYSIS' AND status = 'SUCCESS' ORDER BY id DESC LIMIT 1", (run_id,)).fetchone()
        audit_job = conn.execute("SELECT result_json FROM jobs WHERE run_id = ? AND job_type = 'AUDIT' AND status = 'SUCCESS' ORDER BY id DESC LIMIT 1", (run_id,)).fetchone()

        ai_res = json.loads(ai_job["result_json"]) if ai_job and ai_job["result_json"] else None
        audit_res = json.loads(audit_job["result_json"]) if audit_job and audit_job["result_json"] else None

        audit_issues = conn.execute("SELECT rule_name, issue_type, severity, message, description FROM audit_issues WHERE audit_run_id IN (SELECT id FROM audit_runs WHERE run_id = ?)", (run_id,)).fetchall()

        warnings = []
        if audit_res and isinstance(audit_res, dict) and audit_res.get("warnings"):
            warnings.extend(audit_res.get("warnings"))
        if run["state"] == "UNRESOLVED":
            err_msg = run["error_text"] if "error_text" in run.keys() and run["error_text"] else "insufficient data or audit failed"
            warnings.append(f"Pipeline finished in state UNRESOLVED: {err_msg}")

        return {
            "run_id": run_id,
            "match_id": match_id,
            "state": run["state"],
            "cycle": run["cycle"],
            "data_cutoff_at": data_cutoff_at,
            "claims": claims,
            "claims_count": len(claims),
            "ai_analysis": ai_res,
            "audit": audit_res,
            "audit_issues": [dict(iss) for iss in audit_issues],
            "warnings": warnings,
            "finished_at": run["finished_at"],
        }
    finally:
        conn.close()


@app.post("/api/workers/register", dependencies=[Depends(verify_api_auth)])
def register_worker(worker: WorkerRegistration):
    queue = JobQueue(db_path=DB_PATH)
    queue.store.register_worker(worker.worker_id, worker.capabilities, worker_type=worker.worker_name)
    return {
        "status": "registered",
        "worker_id": worker.worker_id,
    }


@app.post("/api/workers/heartbeat", dependencies=[Depends(verify_api_auth)])
def worker_heartbeat(data: WorkerHeartbeat):
    queue = JobQueue(db_path=DB_PATH)
    queue.store.heartbeat(data.worker_id)
    return {
        "status": "ok",
        "worker_id": data.worker_id,
        "timestamp": now(),
    }


@app.post("/api/jobs/claim", dependencies=[Depends(verify_api_auth)])
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


@app.post("/api/jobs/{job_id}/result", dependencies=[Depends(verify_api_auth)])
def job_result(job_id: str, data: JobResult):
    queue = JobQueue(db_path=DB_PATH)
    with sqlite3.connect(DB_PATH) as conn:
        job_row = conn.execute("SELECT worker_id, status FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
        if not job_row:
            raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
        assigned_worker = job_row[0]
        if assigned_worker is not None and assigned_worker != data.worker_id:
            raise HTTPException(status_code=403, detail=f"Job {job_id} was assigned to worker {assigned_worker}, not {data.worker_id}")

    status_mapped = data.status.upper()
    res_data = data.result if data.result is not None else data.result_json

    if status_mapped == "SUCCESS":
        queue.update_job_status(job_id, "SUCCESS", result=res_data, worker_id=data.worker_id)
    else:
        queue.update_job_status(job_id, "FAILED", error=data.error, worker_id=data.worker_id)

    # Autonomní posun pipeline
    run_id = None
    with queue.store.connect() as conn:
        row = conn.execute("SELECT run_id FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
        if row and row["run_id"]:
            run_id = row["run_id"]

    if run_id:
        master = MasterOrchestrator(db_path=DB_PATH)
        with sqlite3.connect(DB_PATH) as conn:
            for _ in range(5):
                state_before = conn.execute("SELECT state FROM pipeline_runs WHERE run_id = ?", (run_id,)).fetchone()
                master.tick(run_id)
                state_after = conn.execute("SELECT state FROM pipeline_runs WHERE run_id = ?", (run_id,)).fetchone()
                if state_before and state_after and state_before[0] == state_after[0]:
                    break

    return {"status": "ok", "job_id": job_id}
