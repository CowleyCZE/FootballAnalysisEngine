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

            if itype == "conflicting_evidence":
                jobs.append({
                    "job_type": "verify_player_availability",
                    "priority": priority,
                    "match_id": match_id,
                    "reason": issue.get("description"),
                    "status": "pending"
                })
            elif itype in ["missing_evidence", "stale_evidence", "unsupported_claim"]:
                jobs.append({
                    "job_type": "fetch_additional_sources",
                    "priority": priority,
                    "match_id": match_id,
                    "reason": issue.get("description"),
                    "status": "pending"
                })

        return jobs
