import json
import logging
import sqlite3
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


class ContextBuilder:
    def __init__(self, repository=None, db_path: str = "database/football.db"):
        self.repository = repository
        self.db_path = db_path

    def enrich_match_info(self, match_info: Dict[str, Any], match_id: Optional[int]) -> Dict[str, Any]:
        info = dict(match_info or {})
        if not match_id and ("match_id" in info or "id" in info):
            match_id = info.get("match_id") or info.get("id")

        if match_id and self.db_path:
            try:
                with sqlite3.connect(self.db_path) as conn:
                    conn.row_factory = sqlite3.Row
                    row = conn.execute("""
                        SELECT m.id as match_id, m.scheduled_at, m.venue,
                               th.name as home_team, ta.name as away_team, COALESCE(c.name, m.competition, '') as competition
                        FROM matches m
                        LEFT JOIN teams th ON m.home_team_id = th.id
                        LEFT JOIN teams ta ON m.away_team_id = ta.id
                        LEFT JOIN competitions c ON m.competition_id = c.id
                        WHERE m.id = ?
                    """, (match_id,)).fetchone()
                    if row:
                        if not info.get("home_team"):
                            info["home_team"] = row["home_team"] or f"Team_{row['home_team_id'] if 'home_team_id' in row.keys() else match_id}"
                        if not info.get("away_team"):
                            info["away_team"] = row["away_team"] or f"Team_{row['away_team_id'] if 'away_team_id' in row.keys() else match_id}"
                        if not info.get("competition"):
                            info["competition"] = row["competition"] or "Unknown Competition"
                        if not info.get("scheduled_at") and row["scheduled_at"]:
                            info["scheduled_at"] = row["scheduled_at"]
                        if not info.get("venue") and row["venue"]:
                            info["venue"] = row["venue"]
            except Exception as err:
                logger.warning(f"Failed to enrich match_info from DB: {err}")

        if not info.get("data_cutoff_at"):
            if info.get("cutoff_datetime"):
                info["data_cutoff_at"] = info["cutoff_datetime"]
            elif info.get("cutoff"):
                info["data_cutoff_at"] = info["cutoff"]

        info["match_id"] = match_id
        return info

    def load_claims_from_db(self, match_id: int, run_db_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """Load real claims and their supporting evidence from database."""
        claims_list = []
        if not match_id or not self.db_path:
            return claims_list

        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                query = "SELECT * FROM claims WHERE match_id = ? AND status IN ('VALID', 'VERIFIED')"
                params: List[Any] = [match_id]
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
        if not match_id or not self.db_path:
            return {}

        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                row = conn.execute("SELECT * FROM match_statistics WHERE match_id = ?", (match_id,)).fetchone()
                if row:
                    return dict(row)
        except Exception as err:
            logger.warning(f"Failed to load statistics from DB: {err}")

        return {}

    @staticmethod
    def _calculate_freshness_score(claims: List[Dict[str, Any]]) -> float:
        dates = []
        now = datetime.now(timezone.utc)
        for claim in claims:
            for ev in claim.get("evidence", []):
                value = ev.get("published_at")
                if not value:
                    continue
                try:
                    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    if dt <= now:
                        dates.append(dt)
                except (TypeError, ValueError):
                    continue
        if not dates:
            return 0.0
        ages = [(now - dt).total_seconds() / 3600.0 for dt in dates]
        scores = [max(0.0, 1.0 - age / (30.0 * 24.0)) for age in ages]
        return round(sum(scores) / len(scores), 2)

    def build_context(
        self,
        match_info: Dict[str, Any],
        claims: Optional[List[Dict[str, Any]]] = None,
        statistics: Optional[Dict[str, Any]] = None,
        conflicts: Optional[List[Dict[str, Any]]] = None,
        max_claims: int = 30,
        run_db_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        match_id = match_info.get("match_id") or match_info.get("id")
        enriched_match_info = self.enrich_match_info(match_info, match_id)

        if not claims and match_id and self.db_path:
            claims = self.load_claims_from_db(int(match_id), run_db_id)
        else:
            claims = list(claims) if claims is not None else []

        if not statistics and match_id and self.db_path:
            statistics = self.load_statistics_from_db(int(match_id))
        else:
            statistics = dict(statistics) if statistics is not None else {}

        if conflicts is None:
            conflicts = []

        sorted_claims = sorted(
            claims, key=lambda c: c.get("confidence", 0.0), reverse=True
        )[:max_claims]

        formatted_claims = []
        source_urls = set()
        publisher_domains = set()
        official_domains = set()

        for c in sorted_claims:
            evidence_list = c.get("evidence", [])
            formatted_ev = []
            for ev in evidence_list:
                url = ev.get("source_url") or ev.get("url")
                if url:
                    source_urls.add(url)
                    try:
                        domain = urlparse(url).netloc.lower().removeprefix("www.")
                    except Exception:
                        domain = ""
                    if domain:
                        publisher_domains.add(domain)
                    source_type = str(ev.get("source_type") or ev.get("source") or "").lower()
                    if source_type.startswith("official"):
                        official_domains.add(domain)

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
        independent_sources = len(publisher_domains)
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
            "independent_sources": independent_sources,
            "official_sources": len({d for d in official_domains if d}),
            "conflicts": conflicts_count,
            "freshness_score": self._calculate_freshness_score(formatted_claims),
            "missing_data": missing_fields
        }

        return {
            "match": enriched_match_info,
            "statistics": statistics,
            "claims": formatted_claims,
            "conflicts": conflicts,
            "data_quality": data_quality
        }
