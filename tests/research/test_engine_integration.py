import sqlite3

import pytest
from datetime import datetime
from unittest.mock import MagicMock

from app.research.models import ResearchTask, ResearchStatus, ClaimStatus
from app.research.engine import ResearchEngine
from app.research.cutoff_filter import CutoffFilter
from app.research.query_builder import QueryBuilder


@pytest.fixture
def mock_search_client():
    client = MagicMock()
    client.search.return_value = [
        {
            "title": "Arsenal Team News",
            "url": "https://www.bbc.com/sport/football/12345",
            "content": "Bukayo Saka is ruled out of Saturday match due to injury.",
        }
    ]
    return client


@pytest.fixture
def mock_crawler():
    crawler = MagicMock()
    crawler.crawl.return_value = {
        "status": "success",
        "url": "https://www.bbc.com/sport/football/12345",
        "title": "Arsenal Team News",
        "text": "Arsenal confirmed that Bukayo Saka is ruled out of Saturday match due to injury. The winger suffered a knock in training and will be unavailable for selection.",
        "published_at": "2026-10-02T10:00:00Z",
    }
    return crawler


@pytest.fixture
def dummy_task():
    return ResearchTask(
        task_id=1,
        run_id=101,
        match_id=50,
        domain="ABSENCES_HOME",
        task_type="NEWS_COLLECTION",
        description="Absence Arsenal",
        required=True,
        priority=90,
        data_cutoff_at=datetime(2026, 10, 3, 12, 0, 0),
        home_team="Arsenal",
        away_team="Chelsea",
        competition="Premier League",
        scheduled_at=datetime(2026, 10, 3, 15, 0, 0),
    )


def test_cutoff_filter():
    cutoff = datetime(2026, 10, 3, 12, 0, 0)
    valid_date = datetime(2026, 10, 2, 10, 0, 0)
    future_date = datetime(2026, 10, 3, 14, 0, 0)

    passed, reason = CutoffFilter.validate(valid_date, cutoff)
    assert passed is True
    assert reason == "VALID"

    passed, reason = CutoffFilter.validate(future_date, cutoff)
    assert passed is False
    assert reason == "EXCLUDED_BY_CUTOFF"


def test_query_builder(dummy_task):
    qb = QueryBuilder()
    queries = qb.build_queries(dummy_task)
    assert len(queries) > 0
    for q in queries:
        assert "Arsenal" in q["query"]
        assert "None" not in q["query"]


def test_research_engine_execution(mock_search_client, mock_crawler, dummy_task, tmp_path):
    db_file = str(tmp_path / "test_football.db")

    from app.database.research_repository import ResearchRepository

    repo = ResearchRepository(db_path=db_file)
    with sqlite3.connect(db_file) as conn:
        conn.execute(
            "INSERT INTO runs(id, run_id, status, started_at) VALUES (101, 'RUN-101', 'RUNNING', '2026-10-03T10:00:00')"
        )
        conn.execute("INSERT INTO teams(id, name, normalized_name) VALUES (1, 'Arsenal', 'arsenal')")
        conn.execute("INSERT INTO teams(id, name, normalized_name) VALUES (2, 'Chelsea', 'chelsea')")
        conn.execute(
            """
            INSERT INTO matches(id, competition, home_team_id, away_team_id, scheduled_at)
            VALUES (50, 'Premier League', 1, 2, '2026-10-03T15:00:00')
            """
        )
        conn.execute(
            """
            INSERT INTO research_tasks(
                id, run_id, run_db_id, match_id, task_uuid, domain, task_type,
                description, required, priority, capabilities_json, data_cutoff_at,
                home_team, away_team, competition, scheduled_at, status
            ) VALUES (1, 'RUN-101', 101, 50, 'TASK-50-ABSENCES_HOME-C1', 'ABSENCES_HOME',
                      'NEWS_COLLECTION', 'Absence Arsenal', 1, 90, '[]',
                      '2026-10-03T12:00:00', 'Arsenal', 'Chelsea', 'Premier League',
                      '2026-10-03T15:00:00', 'RUNNING')
            """
        )
        conn.commit()

    engine = ResearchEngine(
        search_client=mock_search_client,
        crawler=mock_crawler,
        repository=repo,
    )

    result = engine.execute(dummy_task)

    assert result.status == ResearchStatus.SUCCESS
    assert len(result.claims) >= 1
    assert result.claims[0].subject == "Bukayo Saka"
    assert result.claims[0].status == ClaimStatus.VALID
    assert result.metrics.sources_crawled >= 1

    with sqlite3.connect(db_file) as conn:
        conn.row_factory = sqlite3.Row
        claim = conn.execute("SELECT * FROM claims WHERE run_id=101 AND match_id=50").fetchone()
        assert claim is not None
        evidence = conn.execute(
            """
            SELECT e.*, ce.relationship
            FROM evidence e
            JOIN claim_evidence ce ON ce.evidence_id=e.id
            WHERE ce.claim_id=?
            """,
            (claim["id"],),
        ).fetchone()
        assert evidence is not None
        assert evidence["quoted_text"]
        document = conn.execute("SELECT * FROM documents WHERE id=?", (evidence["document_id"],)).fetchone()
        assert document is not None
        assert document["url"] == "https://www.bbc.com/sport/football/12345"
