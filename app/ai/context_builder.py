import json
import logging
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

class ContextBuilder:
    def __init__(self, repository=None):
        self.repository = repository

    def build_context(
        self,
        match_info: Dict[str, Any],
        claims: List[Dict[str, Any]],
        statistics: Dict[str, Any],
        conflicts: List[Dict[str, Any]] = None,
        max_claims: int = 30,
    ) -> Dict[str, Any]:
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
