from typing import Dict, Any
from app.audit.auditor import AdversarialAuditor
from app.ai.context_builder import ContextBuilder


class AuditWorker:
    @staticmethod
    def execute(payload: Dict[str, Any]) -> Dict[str, Any]:
        match_id = payload.get("match_id", 0)
        run_db_id = payload.get("run_db_id")
        ai_analysis = payload.get("ai_analysis", {})
        claims = payload.get("claims") or []
        statistics = payload.get("statistics") or {}
        cycle = payload.get("cycle", 1)
        db_path = payload.get("db_path", "database/football.db")

        context_builder = ContextBuilder(db_path=db_path)
        if not claims and match_id and db_path:
            claims = context_builder.load_claims_from_db(int(match_id), int(run_db_id) if run_db_id else None)
        if not statistics and match_id and db_path:
            statistics = context_builder.load_statistics_from_db(int(match_id))

        cutoff = payload.get("data_cutoff_at") or ai_analysis.get("match", {}).get("data_cutoff_at")

        auditor = AdversarialAuditor(db_path=db_path)
        return auditor.audit(
            match_id=match_id,
            ai_run_id=payload.get("ai_run_id", "ai-run-1"),
            ai_analysis=ai_analysis,
            claims=claims,
            statistics=statistics,
            current_cycle=cycle,
            data_cutoff_at=cutoff
        )
