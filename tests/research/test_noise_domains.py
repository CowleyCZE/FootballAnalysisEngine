"""TODO 11.20-a – šumové domény (vstupenky, fanshopy, streamy, FM blog) se nestahují ani nepoužijí."""
import pytest

from app.research.source_registry import SourceRegistry
from app.research.source_selector import SourceSelector, is_blocked_source
from app.search.models import SearchResult
from app.search.sport_filter import is_blocked_url, is_football_content, is_noise_domain

NOISE_URLS = [
    "https://livefootballtickets.com/sparta-praha-tickets",
    "https://www.livefootballtickets.com/x",
    "https://fanshop.slavia.cz/dresy",
    "https://eshop.sparta.cz/",
    "https://tickets.example.cz/zapas",
    "https://www.kooralivefree.com/match/1",
    "https://footballmanagerstory.com/story/1",
    "https://sportsdunia.com/football/x",
    "https://m.footballuser.com/a",
    "https://futbor.com/x",
    "https://skorjet.net/live",
]

OK_URLS = [
    "https://www.slavia.cz/zapas/1",
    "https://sparta.cz/cs/zapas/1",
    "https://www.idnes.cz/fotbal/prvni-liga",
    "https://en.wikipedia.org/wiki/AC_Sparta_Prague",
    "https://www.footystats.org/czech-republic",
    "https://notfutbor.com/x",  # jen celá doména / subdoména, ne přípona názvu
]


@pytest.mark.parametrize("url", NOISE_URLS)
def test_noise_domains_are_blocked_everywhere(url):
    assert is_noise_domain(url)
    assert is_blocked_url(url)
    assert is_blocked_source(url, "Sparta Praha – Slovácko", "zápas Chance Ligy")


@pytest.mark.parametrize("url", OK_URLS)
def test_regular_sources_are_not_noise(url):
    assert not is_noise_domain(url)
    assert not is_blocked_source(url, "Sparta Praha – Slovácko", "zápas Chance Ligy")


def test_search_result_from_noise_domain_is_not_football_content():
    result = SearchResult(
        title="Sparta Praha tickets", url="https://livefootballtickets.com/sparta",
        content="Football match tickets", category="general",
    )
    assert not is_football_content(result)


def test_selector_drops_noise_candidates():
    selector = SourceSelector(SourceRegistry())
    results = [
        {"url": "https://fanshop.slavia.cz/dresy", "title": "Slavia dres", "content": "fotbal", "relevance": 95},
        {"url": "https://livefootballtickets.com/x", "title": "Tickets", "content": "fotbal", "relevance": 90},
        {"url": "https://sparta.cz/cs/zapas/1", "title": "Sparta", "content": "zápas", "relevance": 50},
    ]
    assert [c["url"] for c in selector.select_candidates(results)] == ["https://sparta.cz/cs/zapas/1"]
