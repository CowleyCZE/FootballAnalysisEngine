from __future__ import annotations

from typing import Any, Callable, Dict

from app.workers.ai_worker import AIWorker
from app.workers.audit_worker import AuditWorker
from app.workers.crawler_worker import CrawlerWorker
from app.workers.research_worker import ResearchWorker
from app.workers.search_worker import SearchWorker
from app.workers.statistics_worker import StatisticsWorker


Handler = Callable[[Dict[str, Any]], Dict[str, Any]]


def default_handlers() -> Dict[str, Handler]:
    """Return the canonical production job-type -> worker mapping."""
    return {
        "SEARCH": SearchWorker.execute,
        "CRAWL": CrawlerWorker.execute,
        "STATISTICS": StatisticsWorker.execute,
        "RESEARCH": ResearchWorker.execute,
        "AI_ANALYSIS": AIWorker.execute,
        "AUDIT": AuditWorker.execute,
    }
