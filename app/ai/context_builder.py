import json
import logging
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

import sqlite3

class ContextBuilder:
    def __init__(self, repository=None, db_path: str = "database/football.db"):
        self.repository = repository
        self.db_path = db_path

    def load_claims_from_db(self, match_id: int, run_db_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """Load real claims and their supporting evidence from database."""
        claims_list = []
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                query = "SELECT * FROM claims WHERE match_id = ?"
                params = [match_id]
                if run_db_id is not None:
                    query += " AND run_id = ?"
                    params.append(run_db_id)
                claim_rows = conn.execute(query, params).fetchall()

                for c_row in claim_rows:
                    claim_id = c_row["id"]
                    ev_rows = conn.execute("""
                        SELECT e.*, d.url as source_url, d.published_at
                        FROM claim_evidence ce
                        JOIN evidence e ON ce.evidence_id = e.id
                        JOIN documents d ON e.document_id = d.id
                        WHERE ce.claim_id = ?
                    """, (claim_id,)).fetchall()

                    evidence_list = []
                    for ev in ev_rows:
                        evidence_list.append({
                            "evidence_id": ev["id"],
                            "source_url": ev["source_url"],
                            "text_fragment": ev["quoted_text"] or ev["extracted_value"],
                            "published_at": ev["published_at"],
                            "confidence": ev["confidence"]
                        })

                    parts = (c_row["claim_text"] or "").split(" ", 2)
                    subject = parts[0] if parts else ""
                    predicate = parts[1] if len(parts) > 1 else c_row["claim_type"] or ""
                    obj = parts[2] if len(parts) > 2 else c_row["normalized_claim"] or ""

                    claims_list.append({
                        "claim_id": claim_id,
                        "subject": subject,
                        "predicate": predicate,
                        "object": obj,
                        "normalized_value": c_row["normalized_claim"],
                        "confidence": c_row["confidence"] or 0.5,
                        "status": c_row["status"] or "VALID",
                        "evidence": evidence_list
                    })
        except Exception as err:
            logger.warning(f"Failed to load claims from DB: {err}")
        return claims_list

    def load_statistics_from_db(self, match_id: int) -> Dict[str, Any]:
        """Load statistics from database if available."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                row = conn.execute("SELECT * FROM match_statistics WHERE match_id = ?", (match_id,)).fetchone()
                if row:
                    return dict(row)
        except Exception as err:
            logger.warning(f"Failed to load statistics from DB: {err}")
        return {}

    def build_context(
        self,
        match_info: Dict[str, Any],
        claims: List[Dict[str, Any]],
        statistics: Dict[str, Any],
        conflicts: List[Dict[str, Any]] = None,
        max_claims: int = 30,
        run_db_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        match_id = match_info.get("match_id") or match_info.get("id")
        if match_id:
            if not claims:
                claims = self.load_claims_from_db(int(match_id), run_db_id)
            if not statistics:
                statistics = self.load_statistics_from_db(int(match_id))
        if conflicts is None:
            conflicts = []

        sorted_claims = sorted(
            claims, key=lambda c: c.get("confidence", 0.0), reverse=True
        )[:max_claims]

        formatted_claims = []
        source_urls = set()
        official_count = 0

        for c in sorted_claims:
            evidence_list = c.get("evidence", [])
            formatted_ev = []
            for ev in evidence_list:
                url = ev.get("source_url") or ev.get("url")
                if url:
                    source_urls.add(url)
                    if any(domain in url.lower() for domain in ["official", "club", "bbc.com"]):
                        official_count += 1

                formatted_ev.append({
                    "evidence_id": ev.get("id") or ev.get("evidence_id"),
                    "source": ev.get("source", "unknown"),
                    "url": url,
                    "published_at": ev.get("published_at"),
                    "excerpt": ev.get("text_fragment") or ev.get("excerpt", "")
                })

            formatted_claims.append({
                "claim_id": c.get("id") or c.get("claim_id"),
                "subject": c.get("subject"),
                "predicate": c.get("predicate"),
                "object": c.get("object") or c.get("normalized_value"),
                "confidence": c.get("confidence", 0.5),
                "status": c.get("status", "VALID"),
                "evidence": formatted_ev
            })

        missing_fields = []
        if not claims:
            missing_fields.append("claims")
        if not statistics:
            missing_fields.append("statistics")

        total_sources = len(source_urls)
        conflicts_count = len(conflicts)
        
        score = 1.0
        if not claims:
            score -= 0.4
        if not statistics:
            score -= 0.3
        if conflicts_count > 0:
            score -= min(0.2, conflicts_count * 0.05)
        score = max(0.0, min(1.0, round(score, 2)))

        data_quality = {
            "score": score,
            "source_count": total_sources,
            "independent_sources": max(1, total_sources // 2) if total_sources > 0 else 0,
            "official_sources": official_count,
            "conflicts": conflicts_count,
            "freshness_score": 0.95,
            "missing_data": missing_fields
        }

        return {
            "match": match_info,
            "statistics": statistics,
            "claims": formatted_claims,
            "conflicts": conflicts,
            "data_quality": data_quality
        }
