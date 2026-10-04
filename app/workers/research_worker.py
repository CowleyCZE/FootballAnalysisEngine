from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.crawler.crawler import EngineCrawler
from app.research.engine import ResearchEngine
from app.research.models import ResearchStatus, ResearchTask


class _NoopRepository:
    """Compatibility repository used until the DB research schema is unified."""

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
            "retrieved_at": document.retrieved_at,
            "language": document.language,
            "word_count": document.word_count,
            "quality_score": document.quality_score,
            "content_hash": document.content_hash,
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
    """Worker boundary between the job queue and one ResearchEngine task."""

    def __init__(self, db_path: str = "database/football.db", engine: Optional[ResearchEngine] = None):
        self.db_path = db_path
        self.engine = engine or ResearchEngine(repository=_NoopRepository(), crawler=_CrawlerAdapter())

    def execute(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        match = payload.get("match") or {}
        match_id = int(payload.get("match_id") or match.get("id"))
        cutoff = self._parse_datetime(payload.get("cutoff_datetime") or match.get("cutoff_datetime") or match.get("scheduled_at"))
        scheduled_at = self._parse_datetime(match.get("scheduled_at") or cutoff)
        task_id = int(payload["task_id"])

        task = ResearchTask(
            task_id=task_id,
            run_id=int(payload.get("run_db_id") or 0),
            match_id=match_id,
            domain=str(payload["domain"]),
            task_type=str(payload.get("task_type") or "FACT_COLLECTION"),
            description=str(payload.get("description") or ""),
            required=bool(payload.get("required", False)),
            priority=int(payload.get("priority", 50)),
            data_cutoff_at=cutoff,
            home_team=str(match.get("home_team") or ""),
            away_team=str(match.get("away_team") or ""),
            competition=str(match.get("competition") or ""),
            scheduled_at=scheduled_at,
            venue=match.get("venue"),
            attempt_number=int(payload.get("attempt_number", 1)),
        )

        result = self.engine.execute(task)
        status = result.status.value if isinstance(result.status, ResearchStatus) else str(result.status)
        self._update_task_status(task_id, status)

        claims: List[Dict[str, Any]] = [_serialize_claim(claim) for claim in result.claims]
        return {
            "status": status,
            "task_id": task_id,
            "execution_id": result.execution_id,
            "claims": claims,
            "evidence_count": result.evidence_count,
            "sources_count": result.sources_count,
            "documents_count": result.documents_count,
            "conflicts_count": result.conflicts_count,
            "warnings": result.warnings,
            "metrics": result.metrics.__dict__,
        }

    def _update_task_status(self, task_id: int, status: str) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE research_tasks SET status=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (status, task_id),
            )

    @staticmethod
    def _parse_datetime(value: Any) -> datetime:
        if value is None:
            raise ValueError("RESEARCH job requires a data cutoff and scheduled_at")
        if isinstance(value, datetime):
            return value
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
