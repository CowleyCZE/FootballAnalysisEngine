import json
import sqlite3
import uuid
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Tuple

from app.audit.db import init_audit_tables
from app.audit.freshness import FreshnessChecker
from app.audit.conflict_detector import ConflictDetector
from app.audit.evidence_checker import EvidenceChecker
from app.audit.consistency import ConsistencyChecker
from app.audit.repair_queue import RepairQueue

logger = logging.getLogger(__name__)

class AdversarialAuditor:
    def __init__(self, db_path: str = "database/football.db", log_dir: str = "logs/audit"):
        self.db_path = db_path
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        init_audit_tables(self.db_path)

    def audit(
        self,
        match_id: int,
        ai_run_id: str,
        ai_analysis: Dict[str, Any],
        claims: List[Dict[str, Any]],
        statistics: Dict[str, Any],
        max_cycles: int = 3,
        current_cycle: int = 1,
    ) -> Dict[str, Any]:
        run_id = str(uuid.uuid4())
        issues = []

        # 1. Evidence Audit & Hallucination Check
        available_ev_ids = []
        for c in claims:
            for ev in c.get("evidence", []):
                eid = ev.get("id") or ev.get("evidence_id")
                if eid is not None:
                    available_ev_ids.append(eid)

        ev_issues = EvidenceChecker.check_ai_evidence(ai_analysis, available_ev_ids)
        issues.extend(ev_issues)

        # 2. Freshness Audit
        for c in claims:
            for ev in c.get("evidence", []):
                pub_at = ev.get("published_at")
                eid = ev.get("id") or ev.get("evidence_id")
                fresh = FreshnessChecker.calculate_freshness(pub_at, data_type="lineup")
                if fresh["freshness_score"] < 0.3:
                    issues.append({
                        "type": "stale_evidence",
                        "severity": "HIGH",
                        "description": f"Důkaz ID {eid} je zastaralý ({fresh['age_hours']}h starý)",
                        "evidence_ids": [eid] if eid else [],
                        "requires_research": True
                    })

        # 3. Conflict Audit
        conflicts = ConflictDetector.detect_conflicts(claims)
        issues.extend(conflicts)

        # 4. Statistical & Logical Consistency Audit
        stat_issues = ConsistencyChecker.check_statistical_consistency(statistics, claims, ai_analysis)
        issues.extend(stat_issues)

        # Výpočet skóre kvality podkladů
        score = 1.0
        for issue in issues:
            sev = issue.get("severity")
            if sev == "CRITICAL":
                score -= 0.3
            elif sev == "HIGH":
                score -= 0.15
            elif sev == "MEDIUM":
                score -= 0.05
        score = max(0.0, round(score, 2))

        # Tvorba výzkumných úloh
        research_jobs = RepairQueue.generate_research_jobs(match_id, issues)

        # Stanovení statusu
        if current_cycle >= max_cycles and len(research_jobs) > 0:
            status = "UNRESOLVED"
        elif len(research_jobs) > 0:
            status = "RESEARCH_REQUIRED"
        else:
            status = "AUDIT_COMPLETE"

        # Zápis do DB
        self._save_to_db(run_id, match_id, ai_run_id, score, status, issues)

        result = {
            "run_id": run_id,
            "match_id": match_id,
            "ai_run_id": ai_run_id,
            "audit_score": score,
            "status": status,
            "issues": issues,
            "research_jobs": research_jobs,
            "current_cycle": current_cycle,
            "max_cycles": max_cycles
        }

        # Logování do JSON souboru
        log_file = self.log_dir / f"audit_{run_id}.json"
        with open(log_file, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)

        return result

    def _save_to_db(self, run_id: str, match_id: int, ai_run_id: str, score: float, status: str, issues: List[Dict[str, Any]]):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute(
            "INSERT INTO audit_runs (run_id, match_id, ai_run_id, audit_score, status, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (run_id, match_id, ai_run_id, score, status, datetime.now(timezone.utc).isoformat())
        )
        audit_run_pk = cursor.lastrowid

        for issue in issues:
            cursor.execute(
                "INSERT INTO audit_issues (audit_run_id, issue_type, severity, description, requires_research, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    audit_run_pk,
                    issue["type"],
                    issue["severity"],
                    issue["description"],
                    1 if issue.get("requires_research") else 0,
                    datetime.now(timezone.utc).isoformat()
                )
            )
            issue_pk = cursor.lastrowid

            for eid in issue.get("evidence_ids", []):
                cursor.execute("INSERT OR IGNORE INTO audit_issue_evidence (audit_issue_id, evidence_id) VALUES (?, ?)", (issue_pk, eid))
            for cid in issue.get("claim_ids", []):
                cursor.execute("INSERT OR IGNORE INTO audit_issue_claims (audit_issue_id, claim_id) VALUES (?, ?)", (issue_pk, cid))

        conn.commit()
        conn.close()
