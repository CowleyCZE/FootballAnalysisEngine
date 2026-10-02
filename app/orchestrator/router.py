import sqlite3
from typing import Dict, Any
from fastapi import APIRouter, HTTPException, Status, Query

from app.orchestrator.models import AnalysisRequest, ResearchReadiness
from app.orchestrator.orchestrator import MatchOrchestrator
from app.orchestrator.match_resolver import MatchNotFoundException, AmbiguousMatchException
from app.orchestrator.state_machine import RunStatus

router = APIRouter(prefix="/api/analysis", tags=["Analysis Orchestrator"])
orchestrator = MatchOrchestrator()


@router.post("/start", status_code=Status.HTTP_201_CREATED)
def start_analysis(request: AnalysisRequest) -> Dict[str, Any]:
    """
    Zahájí nový proces výzkumu a analýzy pro zadaný zápas.
    """
    try:
        result = orchestrator.start_analysis_run(request)
        return result
    except MatchNotFoundException as e:
        raise HTTPException(
            status_code=Status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except AmbiguousMatchException as e:
        raise HTTPException(
            status_code=Status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=Status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Chyba při spouštění analýzy: {str(e)}"
        )


@router.get("/{run_id}")
def get_analysis_status(run_id: int) -> Dict[str, Any]:
    """
    Vrátí aktuální detail a stav běhu výzkumu (Analysis Run) vč. seznamu úkolů.
    """
    conn = sqlite3.connect(orchestrator.db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM analysis_runs WHERE id = ?", (run_id,))
    run = cursor.fetchone()

    if not run:
        conn.close()
        raise HTTPException(
            status_code=Status.HTTP_404_NOT_FOUND,
            detail=f"Analysis run s ID {run_id} nebyl nalezen."
        )

    cursor.execute("SELECT * FROM research_tasks WHERE run_id = ?", (run_id,))
    tasks = cursor.fetchall()
    conn.close()

    return {
        "run": dict(run),
        "tasks": [dict(t) for t in tasks]
    }


@router.get("/{run_id}/readiness", response_model=ResearchReadiness)
def check_analysis_readiness(run_id: int) -> ResearchReadiness:
    """
    Vyhodnotí připravenost a coverage sesbíraných dat pro spuštění samotné analýzy.
    """
    conn = sqlite3.connect(orchestrator.db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM analysis_runs WHERE id = ?", (run_id,))
    exists = cursor.fetchone()
    conn.close()

    if not exists:
        raise HTTPException(
            status_code=Status.HTTP_404_NOT_FOUND,
            detail=f"Analysis run s ID {run_id} nebyl nalezen."
        )

    return orchestrator.check_readiness(run_id)


@router.post("/{run_id}/cancel")
def cancel_analysis(run_id: int) -> Dict[str, Any]:
    """
    Zruší probíhající běh výzkumu a stornuje otevřené úkoly.
    """
    conn = sqlite3.connect(orchestrator.db_path)
    cursor = conn.cursor()

    cursor.execute("SELECT status FROM analysis_runs WHERE id = ?", (run_id,))
    row = cursor.fetchone()

    if not row:
        conn.close()
        raise HTTPException(
            status_code=Status.HTTP_404_NOT_FOUND,
            detail=f"Analysis run s ID {run_id} nebyl nalezen."
        )

    current_status = row[0]
    if current_status in [RunStatus.CANCELLED, RunStatus.FAILED, RunStatus.READY_FOR_ANALYSIS]:
        conn.close()
        raise HTTPException(
            status_code=Status.HTTP_400_BAD_REQUEST,
            detail=f"Run ve stavu '{current_status}' nelze zrušit."
        )

    # Aktualizace stavu běhu i rozpracovaných úkolů
    cursor.execute(
        "UPDATE analysis_runs SET status = ? WHERE id = ?",
        (RunStatus.CANCELLED, run_id)
    )
    cursor.execute(
        "UPDATE research_tasks SET status = 'CANCELLED' WHERE run_id = ? AND status IN ('PENDING', 'QUEUED', 'CLAIMED', 'RUNNING')",
        (run_id,)
    )

    conn.commit()
    conn.close()

    return {
        "run_id": run_id,
        "status": RunStatus.CANCELLED,
        "message": "Běh výzkumu byl úspěšně zrušen."
    }