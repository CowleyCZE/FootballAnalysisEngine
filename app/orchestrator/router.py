import sqlite3
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, status

import app.api.server as server_module
from app.api.server import verify_api_auth

from app.orchestrator.models import ResearchReadiness
from app.orchestrator.orchestrator import MasterOrchestrator
from app.orchestrator.state_machine import MatchState

# `POST /api/analysis/start` a `GET /api/analysis/{run_id}` jsou registrovány právě jednou,
# v `app/api/server.py` (TODO 5.1). Tento router doplňuje jen readiness a cancel.
router = APIRouter(prefix="/api/analysis", tags=["Analysis Orchestrator"], dependencies=[Depends(verify_api_auth)])


def get_orchestrator() -> MasterOrchestrator:
    """Orchestrátor se vytváří líně a nad aktuální cestou DB (`server.DB_PATH`), ne při importu modulu."""
    return MasterOrchestrator(db_path=server_module.DB_PATH)


@router.get("/{run_id}/readiness", response_model=ResearchReadiness)
def check_analysis_readiness(run_id: str) -> ResearchReadiness:
    """Vyhodnotí, zda má pipeline dostatek dokončených podkladů pro AI analýzu."""
    with sqlite3.connect(server_module.DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        run = conn.execute(
            "SELECT * FROM pipeline_runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        jobs = conn.execute(
            "SELECT job_type, status FROM jobs WHERE run_id = ?", (run_id,)
        ).fetchall()
    if not run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pipeline run nebyl nalezen.")

    required_types = {"SEARCH", "STATISTICS"}
    completed = {row["job_type"] for row in jobs if row["status"] == "SUCCESS"}
    required_complete = required_types.issubset(completed)
    state = run["state"]
    ready = required_complete and state in {
        MatchState.ANALYZING,
        MatchState.AUDITING,
        MatchState.FINALIZING,
        MatchState.COMPLETED,
    }
    warnings = [] if required_complete else ["Požadované discovery/statistics Joby nejsou dokončené."]
    return ResearchReadiness(
        ready=ready,
        required_complete=required_complete,
        coverage_score=1.0 if required_complete else len(completed) / len(required_types),
        critical_conflicts=0,
        warnings=warnings,
        blocking_reasons=[] if ready else [f"Pipeline je ve stavu {state}"],
    )


@router.post("/{run_id}/cancel")
def cancel_analysis(run_id: str) -> Dict[str, Any]:
    """Zastaví běh pipeline a zruší dosud nespouštěné Joby."""
    orchestrator = get_orchestrator()
    with sqlite3.connect(orchestrator.db_path) as conn:
        conn.row_factory = sqlite3.Row
        run = conn.execute(
            "SELECT state FROM pipeline_runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        if not run:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pipeline run nebyl nalezen.")
        conn.execute(
            "UPDATE jobs SET status='CANCELLED', finished_at=CURRENT_TIMESTAMP WHERE run_id=? AND status IN ('PENDING','BLOCKED','RETRY')",
            (run_id,),
        )
    orchestrator.state_machine.transition_to(run_id, MatchState.FAILED, "Cancelled by API")
    return {"run_id": run_id, "status": "CANCELLED", "message": "Běh pipeline byl zastaven."}
