from typing import List, Dict, Any
import logging

logger = logging.getLogger(__name__)


class RepairQueue:
    @staticmethod
    def generate_research_jobs(match_id: int, issues: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        jobs = []

        for issue in issues:
            if not issue.get("requires_research", False):
                continue

            itype = issue.get("type")
            severity = issue.get("severity", "MEDIUM")

            priority_map = {
                "CRITICAL": 100,
                "HIGH": 90,
                "MEDIUM": 60,
                "LOW": 30
            }
            priority = priority_map.get(severity, 50)
            desc = issue.get("description", "Audit repair required")

            if itype == "conflicting_evidence":
                domain = "ABSENCES_HOME"
                job_type = "verify_player_availability"
            elif itype in ["missing_evidence", "stale_evidence", "unsupported_claim", "cutoff_violation"]:
                domain = "GENERAL"
                job_type = "fetch_additional_sources"
            else:
                domain = "GENERAL"
                job_type = "RESEARCH"

            jobs.append({
                "job_type": job_type,
                "domain": domain,
                "priority": priority,
                "match_id": match_id,
                "reason": desc,
                "description": desc,
                "status": "pending"
            })

        return jobs
