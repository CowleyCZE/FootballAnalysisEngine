import sqlite3
from typing import List
from app.orchestrator.models import ResearchReadiness
from app.orchestrator.policies import ResearchPolicy

class CoverageEngine:
    def __init__(self, db_path: str = "database/football.db"):
        self.db_path = db_path

    def evaluate_run(self, run_id: int) -> ResearchReadiness:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Načteme všechny úkoly daného runu
        cursor.execute("SELECT domain, required, status FROM research_tasks WHERE run_id = ?", (run_id,))
        tasks = cursor.fetchall()

        # Načteme otevřené konflikty
        cursor.execute("SELECT domain, severity FROM research_conflicts WHERE run_id = ? AND status = 'OPEN'", (run_id,))
        conflicts = cursor.fetchall()
        conn.close()

        if not tasks:
            return ResearchReadiness(
                ready=False,
                required_complete=False,
                coverage_score=0.0,
                critical_conflicts=len(conflicts),
                blocking_reasons=["Žádné tasky nenalezeny."]
            )

        total_tasks = len(tasks)
        completed_tasks = sum(1 for t in tasks if t["status"] == "COMPLETED")
        
        required_tasks = [t for t in tasks if t["required"] == 1]
        required_completed = sum(1 for t in required_tasks if t["status"] == "COMPLETED")
        
        all_required_done = (len(required_tasks) == required_completed)
        coverage_score = round(completed_tasks / total_tasks, 2)
        
        critical_conflicts = sum(1 for c in conflicts if c["severity"] in ["HIGH", "CRITICAL"])

        blocking_reasons = []
        if not all_required_done:
            missing = [t["domain"] for t in required_tasks if t["status"] != "COMPLETED"]
            blocking_reasons.append(f"Chybí dokončení povinných domén: {', '.join(missing)}")
        
        if critical_conflicts > 0:
            blocking_reasons.append(f"Nalezeno {critical_conflicts} nevyřešených kritických konfliktů v datech.")

        if coverage_score < ResearchPolicy.MIN_COVERAGE_SCORE:
            blocking_reasons.append(f"Celkové coverage ({coverage_score}) nedosahuje požadované hranice ({ResearchPolicy.MIN_COVERAGE_SCORE}).")

        is_ready = all_required_done and (critical_conflicts == 0) and (coverage_score >= ResearchPolicy.MIN_COVERAGE_SCORE)

        return ResearchReadiness(
            ready=is_ready,
            required_complete=all_required_done,
            coverage_score=coverage_score,
            critical_conflicts=critical_conflicts,
            blocking_reasons=blocking_reasons
        )