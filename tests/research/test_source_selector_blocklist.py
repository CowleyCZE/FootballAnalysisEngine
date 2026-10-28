"""Reálný běh M589: crawler stahoval porno weby z výsledků vyhledávání – selektor je musí vyřadit."""
import pytest

from app.research.source_registry import SourceRegistry
from app.research.source_selector import SourceSelector, is_blocked_source


@pytest.mark.parametrize(
    "url",
    [
        "https://www.xvideos.com/tags/big-natural-tits",
        "https://cz.pornhub.com/video/search?search=all+natural+big+tits",
        "https://fans.rip/models/noarmsgirl",
        "https://coomer.st/onlyfans/user/noarmsgirl?o=250",
        "https://www.erome.com/search?q=no+arms",
        "https://thefappeningblog.com/forum/threads/x.1",
    ],
)
def test_adult_domains_are_blocked(url):
    assert is_blocked_source(url)


def test_adult_text_in_title_or_snippet_is_blocked():
    assert is_blocked_source("https://example.com/a", "Leaked nudes", "")
    assert is_blocked_source("https://example.com/a", "", "watch porn online")


@pytest.mark.parametrize(
    "url",
    [
        "https://sparta.cz/cs/zapas/1",
        "https://en.wikipedia.org/wiki/AC_Sparta_Prague",
        "https://www.sussexcricket.co.uk/x",
        "https://www.idnes.cz/fotbal/prvni-liga",
    ],
)
def test_normal_sources_are_not_blocked(url):
    assert not is_blocked_source(url, "Sparta Praha – Slovácko", "Zápas Chance Ligy")


def test_selector_drops_blocked_candidates():
    selector = SourceSelector(SourceRegistry())
    results = [
        {"url": "https://www.xvideos.com/tags/x", "title": "x", "content": "", "relevance": 90},
        {"url": "https://sparta.cz/cs/zapas/1", "title": "Sparta", "content": "zápas", "relevance": 50},
    ]
    selected = selector.select_candidates(results)
    assert [c["url"] for c in selected] == ["https://sparta.cz/cs/zapas/1"]
