from typing import Dict, Any
from app.audit.auditor import AdversarialAuditor

class AuditWorker:
    @staticmethod
    def execute(payload: Dict[str, Any]) -> Dict[str, Any]:
        match_id = payload.get("match_id", 0)
        ai_analysis = payload.get("ai_analysis", {})
        claims = payload.get("claims", [])
        statistics = payload.get("statistics", {})
        cycle = payload.get("cycle", 1)

        auditor = AdversarialAuditor()
        return auditor.audit(
            match_id=match_id,
            ai_run_id=payload.get("ai_run_id", "ai-run-1"),
            ai_analysis=ai_analysis,
            claims=claims,
            statistics=statistics,
            current_cycle=cycle
        )
