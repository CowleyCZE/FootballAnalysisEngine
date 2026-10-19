from app.search.source_registry import SearchSourceRegistry
from app.research.source_registry import SourceRegistry


def test_search_and_research_registry_share_the_same_classification():
    search_registry = SearchSourceRegistry()
    research_registry = SourceRegistry()

    for url in (
        "https://www.arsenal.com/news/example",
        "https://www.bbc.com/sport/football/example",
        "https://www.unknown-example.test/story",
    ):
        assert search_registry.get_info(url) == research_registry.get_domain_info(url)


def test_registry_uses_shared_yaml_configuration():
    registry = SearchSourceRegistry()

    assert registry.get_info("https://www.fcbayern.com/news/example")["authority"] == 1.0
    assert registry.get_info("https://www.bbc.co.uk/sport/example")["source_type"] == "major_news"
    assert registry.get_info("https://unknown.example/article")["source_type"] == "unknown"
    assert registry.get_info("https://unknown.example/article")["authority"] == 0.2
