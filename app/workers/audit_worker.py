from typing import Any, Dict

from app.audit.auditor import AdversarialAuditor


class AuditWorker:
    @staticmethod
    def execute(payload: Dict[str, Any]) -> Dict[str, Any]:
        match_id = int(payload.get("match_id"))
        run_id = str(payload.get("run_id") or "")
        if not run_id:
            raise ValueError("AUDIT job requires run_id")

        auditor = AdversarialAuditor()
        return auditor.audit(
            match_id=match_id,
            ai_run_id=run_id,
            ai_analysis=payload.get("ai_analysis") or {},
            claims=payload.get("claims") or [],
            statistics=payload.get("statistics") or {},
            current_cycle=int(payload.get("cycle", 1)),
            max_cycles=int(payload.get("max_cycles", 3)),
        )
