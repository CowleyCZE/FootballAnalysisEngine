from app.search.models import SearchResult, QuerySpec
from app.search.deduplicator import canonicalize_url, deduplicate
from app.search.relevance import calculate_relevance


def test_canonicalize_removes_tracking_parameters():
    url = (
        "HTTPS://Example.COM/article/"
        "?utm_source=test&x=1&fbclid=abc"
    )

    assert canonicalize_url(url) == "https://example.com/article?x=1"


def test_deduplicate_same_canonical_url():
    results = [
        SearchResult(
            title="Article",
            url="https://example.com/a?utm_source=x",
            content="text",
        ),
        SearchResult(
            title="Article duplicate",
            url="https://EXAMPLE.com/a",
            content="different",
        ),
    ]

    unique = deduplicate(results)

    assert len(unique) == 1
    assert unique[0].title == "Article"


def test_relevance_prefers_team_in_title():
    result = SearchResult(
        title="Sparta Praha injury update",
        url="https://example.com/sparta",
        content="Sparta Praha has several unavailable players",
    )

    score = calculate_relevance(
        result,
        "Sparta Praha",
        ["injury", "injuries", "zranění"],
    )

    assert score >= 45


def test_query_spec_defaults():
    query = QuerySpec(query="Sparta Praha injuries")

    assert query.language == "all"
    assert query.priority == 50
    assert query.time_range is None
    assert query.reason == ""


class FakeSearchClient:
    async def search(
        self,
        query,
        language="all",
        page=1,
        time_range=None,
    ):
        return {
            "results": [
                {
                    "title": "Sparta Praha injury update",
                    "url": "https://sparta.cz/news/injury?utm_source=test",
                    "content": "Sparta Praha has injury news.",
                    "engine": "test",
                    "score": 2.0,
                },
                {
                    "title": "Sparta Praha injury duplicate",
                    "url": "https://SPARTA.CZ/news/injury",
                    "content": "duplicate",
                    "engine": "test",
                    "score": 1.0,
                },
                {
                    "title": "Other football news",
                    "url": "https://example.com/football",
                    "content": "football news",
                    "engine": "test",
                    "score": 1.0,
                },
            ]
        }


def test_search_engine_normalizes_deduplicates_and_ranks():
    from app.search.engine import SearchEngine

    engine = SearchEngine(
        client=FakeSearchClient(),
    )

    import asyncio

    results = asyncio.run(
        engine.search(
            QuerySpec(
                query="Sparta Praha injuries",
                language="cs",
            ),
            team="Sparta Praha",
            topic_terms=["injury", "injuries", "zranění"],
        )
    )

    assert len(results) == 2
    assert results[0].title == "Sparta Praha injury update"
    assert results[0].relevance > results[1].relevance
    assert results[0].source_type == "official_club"


def test_search_engine_excludes_results_after_cutoff():
    from app.search.engine import SearchEngine
    import asyncio
    from datetime import datetime

    class CutoffClient:
        async def search(self, query, language="all", time_range=None):
            return {
                "results": [
                    {
                        "title": "Arsenal squad news",
                        "url": "https://news.example/before",
                        "content": "injury update",
                        "published_at": "2026-10-01T10:00:00Z",
                        "score": 1.0,
                    },
                    {
                        "title": "Arsenal squad news",
                        "url": "https://news.example/after",
                        "content": "injury update",
                        "published_at": "2026-10-04T10:00:00Z",
                        "score": 2.0,
                    },
                ]
            }

    engine = SearchEngine(client=CutoffClient())
    results = asyncio.run(
        engine.search(
            QuerySpec(query="Arsenal injuries"),
            team="Arsenal",
            topic_terms=["injury"],
            data_cutoff_at=datetime.fromisoformat("2026-10-03T12:00:00+00:00"),
        )
    )
    assert [r.url for r in results] == ["https://news.example/before"]


def test_relevance_handles_zulu_cutoff_dates():
    from datetime import datetime, timezone
    result = SearchResult(
        title="Arsenal news",
        url="https://news.example/article",
        content="injury",
        published_at="2026-10-03T11:00:00Z",
    )
    score = calculate_relevance(
        result,
        "Arsenal",
        ["injury"],
        data_cutoff_at=datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc),
    )
    assert score > 0
