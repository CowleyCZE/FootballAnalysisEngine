from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Dict, List

from app.crawler.crawler import EngineCrawler
from app.research.engine import ResearchEngine
from app.research.models import ResearchTask


class _NoopRepository:
    """ResearchRepository boundary for orchestration jobs.

    Pipeline job results are the transport for this worker. Persistent claim /
    evidence storage is deliberately left to the pipeline database layer.
    """

    def create_execution(self, *args):
        return 0

    def create_session(self, *args):
        return 0

    def save_query(self, *args, **kwargs):
        return None

    def save_source_candidate(self, *args, **kwargs):
        return None

    def complete_execution(self, *args, **kwargs):
        return None

    def save_claims_and_evidence(self, *args, **kwargs):
        return None


class _CrawlerAdapter:
    def __init__(self):
        self.crawler = EngineCrawler()

    def crawl(self, url: str) -> Dict[str, Any]:
        result, document = asyncio.run(self.crawler.crawl_and_parse(url))
        if not result.success or document is None:
            return {"status": "error", "url": url, "error": result.error or "crawl failed"}
        return {
            "status": "success",
            "url": document.url,
            "title": document.title or "",
            "text": document.text or "",
            "published_at": document.published_at,
            "language": document.language,
        }


def _serialize_claim(claim: Any) -> Dict[str, Any]:
    return {
        "claim_id": claim.claim_id,
        "subject": claim.subject,
        "predicate": claim.predicate,
        "object": claim.object_value,
        "normalized_value": claim.normalized_value,
        "confidence": claim.confidence,
        "status": claim.status.value if hasattr(claim.status, "value") else str(claim.status),
        "source_date": claim.source_date.isoformat() if claim.source_date else None,
        "evidence": [
            {
                "document_id": ev.document_id,
                "source_url": ev.source_url,
                "text_fragment": ev.text_fragment,
                "published_at": ev.published_at.isoformat() if ev.published_at else None,
            }
            for ev in claim.evidence_list
        ],
    }


class ResearchWorker:
    @staticmethod
    def execute(payload: Dict[str, Any]) -> Dict[str, Any]:
        match = payload.get("match") or {}
        match_id = int(payload.get("match_id") or match.get("id"))
        domains = payload.get("domains") or ["MATCH_IDENTITY", "RECENT_FORM", "ABSENCES_HOME", "ABSENCES_AWAY", "WEATHER"]
        cutoff = payload.get("cutoff_datetime") or match.get("cutoff_datetime") or match.get("scheduled_at")
        scheduled_at = match.get("scheduled_at") or cutoff
        if not cutoff or not scheduled_at:
            raise ValueError("RESEARCH job requires cutoff_datetime and scheduled_at")

        if isinstance(cutoff, str):
            cutoff = datetime.fromisoformat(cutoff.replace("Z", "+00:00"))
        if isinstance(scheduled_at, str):
            scheduled_at = datetime.fromisoformat(scheduled_at.replace("Z", "+00:00"))

        common = dict(
            run_id=0,
            match_id=match_id,
            task_type="NEWS_COLLECTION",
            required=True,
            priority=int(payload.get("priority", 80)),
            data_cutoff_at=cutoff,
            home_team=str(match.get("home_team") or ""),
            away_team=str(match.get("away_team") or ""),
            competition=str(match.get("competition") or ""),
            scheduled_at=scheduled_at,
        )

        engine = ResearchEngine(repository=_NoopRepository(), crawler=_CrawlerAdapter())
        results = []
        for index, domain in enumerate(domains, start=1):
            task = ResearchTask(
                task_id=index,
                domain=str(domain),
                description=f"Research orchestration: {domain}",
                **common,
            )
            result = engine.execute(task)
            results.append(result)

        claims: List[Dict[str, Any]] = []
        warnings: List[str] = []
        metrics = {"tasks": len(results), "successful_tasks": 0, "claims": 0, "evidence": 0}
        for result in results:
            if result.status.value in {"SUCCESS", "PARTIAL", "CONFLICTED"}:
                metrics["successful_tasks"] += 1
            warnings.extend(result.warnings)
            for claim in result.claims:
                serialized = _serialize_claim(claim)
                claims.append(serialized)
                metrics["claims"] += 1
                metrics["evidence"] += len(serialized["evidence"])

        return {
            "status": "COMPLETED" if results and any(r.status.value == "SUCCESS" for r in results) else "NO_RESULT",
            "match_id": match_id,
            "claims": claims,
            "evidence_count": metrics["evidence"],
            "warnings": warnings,
            "metrics": metrics,
        }
