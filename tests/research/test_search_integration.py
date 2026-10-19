from datetime import datetime
from unittest.mock import MagicMock

from app.research.models import ResearchTask
from app.research.search_adapter import SearchAdapter
from app.research.topic_terms import get_topic_terms
from app.search.models import QuerySpec, SearchResult


def test_topic_terms_are_deterministic():
    terms = get_topic_terms("ABSENCES_HOME")

    assert "injury" in terms
    assert "absence" in terms
    assert get_topic_terms("UNKNOWN_DOMAIN") == []


class FakeUnifiedSearchEngine:
    def __init__(self):
        self.calls = []

    async def search(self, query, team="", topic_terms=None):
        self.calls.append((query, team, topic_terms))
        return [
            SearchResult(
                title="Arsenal injury update",
                url="https://arsenal.com/news/injury",
                content="Official injury update.",
                relevance=92,
                source_type="official_club",
            )
        ]


def test_search_adapter_forwards_query_context():
    fake = FakeUnifiedSearchEngine()
    adapter = SearchAdapter(search_engine=fake)

    results = adapter.search(
        "Arsenal injuries",
        team="Arsenal",
        domain="ABSENCES_HOME",
        priority=90,
        reason="DISCOVERY",
    )

    assert len(results) == 1
    assert results[0].source_type == "official_club"
    assert fake.calls[0][0].query == "Arsenal injuries"
    assert fake.calls[0][1] == "Arsenal"
    assert "injury" in fake.calls[0][2]


def test_search_adapter_accepts_query_spec():
    fake = FakeUnifiedSearchEngine()
    adapter = SearchAdapter(search_engine=fake)

    spec = QuerySpec(
        query="Arsenal official injury update",
        language="en",
        priority=95,
        reason="PRIMARY",
    )

    results = adapter.search(
        spec,
        team="Arsenal",
        domain="ABSENCES_HOME",
    )

    assert len(results) == 1
    assert fake.calls[0][0] is spec


def test_research_task_context_matches_adapter_contract():
    task = ResearchTask(
        task_id=1,
        run_id=1,
        match_id=1,
        domain="ABSENCES_HOME",
        task_type="NEWS_COLLECTION",
        description="Arsenal absences",
        required=True,
        priority=90,
        data_cutoff_at=datetime(2026, 10, 3, 12, 0, 0),
        home_team="Arsenal",
        away_team="Chelsea",
        competition="Premier League",
        scheduled_at=datetime(2026, 10, 3, 15, 0, 0),
    )

    fake = FakeUnifiedSearchEngine()
    adapter = SearchAdapter(search_engine=fake)

    results = adapter.search(
        "Arsenal injuries",
        team=task.home_team,
        domain=task.domain,
        priority=task.priority,
    )

    assert results
    assert fake.calls[0][1] == task.home_team
    assert "injury" in fake.calls[0][2]
