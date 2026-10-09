import sqlite3
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, status

from app.orchestrator.models import AnalysisRequest, ResearchReadiness
from app.orchestrator.orchestrator import MasterOrchestrator
from app.orchestrator.match_resolver import MatchNotFoundException, AmbiguousMatchException
from app.orchestrator.state_machine import MatchState

router = APIRouter(prefix="/api/analysis", tags=["Analysis Orchestrator"])
orchestrator = MasterOrchestrator()


@router.post("/start", status_code=status.HTTP_201_CREATED)
def start_analysis(request: AnalysisRequest) -> Dict[str, Any]:
    """Zahájí autonomní pipeline pro ověřený zápas přes MasterOrchestrator a MatchResolver."""
    try:
        run_id = orchestrator.start_pipeline_from_request(request)
        return {"run_id": run_id, "status": MatchState.DISCOVERY}
    except MatchNotFoundException as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except AmbiguousMatchException as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Chyba při spuštění analýzy: {exc}",
        ) from exc


@router.get("/{run_id}")
def get_analysis_status(run_id: str) -> Dict[str, Any]:
    """Vrátí stav pipeline a všechny Joby patřící k danému běhu."""
    with sqlite3.connect(orchestrator.db_path) as conn:
        conn.row_factory = sqlite3.Row
        run = conn.execute(
            "SELECT * FROM pipeline_runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        if not run:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pipeline run nebyl nalezen.")
        jobs = conn.execute(
            "SELECT * FROM jobs WHERE run_id = ? ORDER BY id", (run_id,)
        ).fetchall()
    return {"run": dict(run), "jobs": [dict(job) for job in jobs]}


@router.get("/{run_id}/readiness", response_model=ResearchReadiness)
def check_analysis_readiness(run_id: str) -> ResearchReadiness:
    """Vyhodnotí, zda má pipeline dostatek dokončených podkladů pro AI analýzu."""
    with sqlite3.connect(orchestrator.db_path) as conn:
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
        conn.execute(
            "UPDATE pipeline_runs SET state=?, updated_at=CURRENT_TIMESTAMP, finished_at=CURRENT_TIMESTAMP, error_text=? WHERE run_id=?",
            (MatchState.FAILED, "Cancelled by API", run_id),
        )
        conn.execute(
            "UPDATE runs SET status=?, finished_at=CURRENT_TIMESTAMP WHERE run_id=?",
            (MatchState.FAILED, run_id),
        )
    return {"run_id": run_id, "status": "CANCELLED", "message": "Běh pipeline byl zastaven."}
