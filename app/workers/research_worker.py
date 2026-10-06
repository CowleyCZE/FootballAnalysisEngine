from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.crawler.crawler import EngineCrawler
from app.database.research_repository import ResearchRepository
from app.research.engine import ResearchEngine
from app.research.models import ResearchStatus, ResearchTask


class _CrawlerAdapter:
    def __init__(self):
        self.crawler = EngineCrawler()

    def crawl(self, url: str) -> Dict[str, Any]:
        result, document = asyncio.run(self.crawler.crawl_and_parse(url))
        if not result.success or document is None:
            return {"status": "error", "url": url, "error": result.error or "crawl failed"}
        return {"status": "success", "url": document.url, "title": document.title or "", "text": document.text or "", "published_at": document.published_at, "retrieved_at": document.retrieved_at, "language": document.language, "word_count": document.word_count, "quality_score": document.quality_score, "content_hash": document.content_hash}


def _serialize_claim(claim: Any) -> Dict[str, Any]:
    return {"claim_id": claim.claim_id, "subject": claim.subject, "predicate": claim.predicate, "object": claim.object_value, "normalized_value": claim.normalized_value, "confidence": claim.confidence, "status": claim.status.value if hasattr(claim.status, "value") else str(claim.status), "source_date": claim.source_date.isoformat() if claim.source_date else None, "evidence": [{"document_id": ev.document_id, "source_url": ev.source_url, "text_fragment": ev.text_fragment, "published_at": ev.published_at.isoformat() if ev.published_at else None} for ev in claim.evidence_list]}


class ResearchWorker:
    """Worker boundary between the job queue and one ResearchEngine task."""

    def __init__(self, db_path: str = "database/football.db", engine: Optional[ResearchEngine] = None):
        self.db_path = db_path
        self.repository = ResearchRepository(db_path=db_path)
        self.engine = engine or ResearchEngine(repository=self.repository, crawler=_CrawlerAdapter())

    @classmethod
    def execute(cls, payload: Dict[str, Any]) -> Dict[str, Any]:
        db_path = payload.get("db_path") or "database/football.db"
        worker = cls(db_path=db_path)
        return worker.run_execute(payload)

    def _resolve_match_context(self, match_id: int, payload: Dict[str, Any], match: Dict[str, Any]) -> Dict[str, Any]:
        home_team = payload.get("home_team") or match.get("home_team")
        away_team = payload.get("away_team") or match.get("away_team")
        competition = payload.get("competition") or match.get("competition")
        venue = payload.get("venue") or match.get("venue")
        scheduled_raw = payload.get("scheduled_at") or match.get("scheduled_at")
        cutoff_raw = payload.get("cutoff_datetime") or payload.get("cutoff") or match.get("cutoff_datetime") or match.get("cutoff") or scheduled_raw

        if not home_team or not away_team or not competition or str(home_team).isdigit() or str(away_team).isdigit() or not scheduled_raw:
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
                    if not home_team or str(home_team).isdigit():
                        home_team = row["home_team"]
                    if not away_team or str(away_team).isdigit():
                        away_team = row["away_team"]
                    if not competition or str(competition).isdigit():
                        competition = row["competition"]
                    if not venue:
                        venue = row["venue"]
                    if not scheduled_raw:
                        scheduled_raw = row["scheduled_at"]
                    if not cutoff_raw:
                        cutoff_raw = scheduled_raw

        cutoff = self._parse_datetime(cutoff_raw) if cutoff_raw else datetime.now(timezone.utc)
        scheduled_at = self._parse_datetime(scheduled_raw) if scheduled_raw else cutoff

        return {
            "home_team": str(home_team or f"Team_{match_id}"),
            "away_team": str(away_team or f"Opponent_{match_id}"),
            "competition": str(competition or "Football League"),
            "venue": venue,
            "scheduled_at": scheduled_at,
            "data_cutoff_at": cutoff,
        }

    def run_execute(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        match = payload.get("match") or {}
        match_id = int(payload.get("match_id") or match.get("id") or 0)
        ctx = self._resolve_match_context(match_id, payload, match)

        task_id = payload.get("task_id")
        domain = str(payload.get("domain") or "GENERAL")
        run_id_str = str(payload.get("run_id") or "")
        run_db_id = int(payload.get("run_db_id") or 0)

        if not task_id:
            task_uuid = str(payload.get("task_uuid") or f"TASK-{match_id}-{domain}")
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                row = conn.execute("SELECT id FROM research_tasks WHERE run_id=? AND task_uuid=?", (run_id_str, task_uuid)).fetchone()
                if row:
                    task_id = int(row["id"])
                else:
                    cur = conn.execute("""
                        INSERT INTO research_tasks(run_id, run_db_id, match_id, task_uuid, domain, task_type, description, required, priority, capabilities_json, data_cutoff_at, home_team, away_team, competition, scheduled_at, venue, status)
                        VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, '[]', ?, ?, ?, ?, ?, ?, 'RUNNING')
                    """, (run_id_str, run_db_id if run_db_id else None, match_id, task_uuid, domain, str(payload.get("task_type") or "FACT_COLLECTION"), str(payload.get("description") or f"Research for {domain}"), 0, int(payload.get("priority", 50)), ctx["data_cutoff_at"].isoformat(), ctx["home_team"], ctx["away_team"], ctx["competition"], ctx["scheduled_at"].isoformat(), ctx["venue"]))
                    conn.commit()
                    task_id = int(cur.lastrowid)
        else:
            task_id = int(task_id)

        attempt_number = int(payload.get("_job_attempt_number") or payload.get("attempt_number") or self._task_attempt(task_id))

        task = ResearchTask(
            task_id=task_id,
            run_id=run_db_id,
            match_id=match_id,
            domain=domain,
            task_type=str(payload.get("task_type") or "FACT_COLLECTION"),
            description=str(payload.get("description") or f"Research for {domain}"),
            required=bool(payload.get("required", False)),
            priority=int(payload.get("priority", 50)),
            data_cutoff_at=ctx["data_cutoff_at"],
            home_team=ctx["home_team"],
            away_team=ctx["away_team"],
            competition=ctx["competition"],
            scheduled_at=ctx["scheduled_at"],
            venue=ctx["venue"],
            attempt_number=attempt_number,
        )

        result = self.engine.execute(task)
        status = result.status.value if isinstance(result.status, ResearchStatus) else str(result.status)
        claims: List[Dict[str, Any]] = [_serialize_claim(claim) for claim in result.claims]
        return {"status": status, "task_id": task_id, "execution_id": result.execution_id, "claims": claims, "evidence_count": result.evidence_count, "sources_count": result.sources_count, "documents_count": result.documents_count, "conflicts_count": result.conflicts_count, "warnings": result.warnings, "metrics": result.metrics.__dict__}

    def _task_attempt(self, task_id: int) -> int:
        row = self.repository.get_task(task_id)
        if not row:
            raise KeyError(task_id)
        return int(row["attempt_number"] or 1)

    @staticmethod
    def _parse_datetime(value: Any) -> datetime:
        if value is None:
            raise ValueError("RESEARCH job requires a data cutoff and scheduled_at")
        if isinstance(value, datetime):
            return value
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
