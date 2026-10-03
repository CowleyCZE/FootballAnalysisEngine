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
            "content": "Bukayo Saka is ruled out of Saturday match due to injury."
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
        "published_at": "2026-10-02T10:00:00Z"
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
        scheduled_at=datetime(2026, 10, 3, 15, 0, 0)
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
    
    import sqlite3
    conn = sqlite3.connect(db_file)
    conn.execute("CREATE TABLE analysis_runs (id INTEGER PRIMARY KEY);")
    conn.execute("INSERT INTO analysis_runs VALUES (101);")
    conn.execute("CREATE TABLE research_tasks (id INTEGER PRIMARY KEY);")
    conn.execute("INSERT INTO research_tasks VALUES (1);")
    conn.execute("CREATE TABLE claims (id INTEGER PRIMARY KEY AUTOINCREMENT, run_id INT, match_id INT, task_id INT, subject TEXT, predicate TEXT, object TEXT, normalized_value TEXT, source_date TEXT, confidence REAL, status TEXT);")
    conn.execute("CREATE TABLE evidence (id INTEGER PRIMARY KEY AUTOINCREMENT, claim_id INT, document_id INT, source_url TEXT, text_fragment TEXT, published_at TEXT, retrieved_at TEXT);")
    conn.commit()
    conn.close()

    from app.database.research_repository import ResearchRepository
    repo = ResearchRepository(db_path=db_file)

    engine = ResearchEngine(
        search_client=mock_search_client,
        crawler=mock_crawler,
        repository=repo
    )

    result = engine.execute(dummy_task)

    assert result.status == ResearchStatus.SUCCESS
    assert len(result.claims) >= 1
    assert result.claims[0].subject == "Bukayo Saka"
    assert result.claims[0].status == ClaimStatus.VALID
    assert result.metrics.sources_crawled >= 1
