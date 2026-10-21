"""TODO 3.5 – registr zdrojů: české a statistické domény, subdomény."""
import pytest

from app.search.source_registry import SearchSourceRegistry


@pytest.fixture(scope="module")
def reg():
    return SearchSourceRegistry("config/source_registry.yaml")


@pytest.mark.parametrize("url,expected", [
    ("https://www.fotbal.cz/zapas/1", "official_league"),
    ("https://www.fortunaliga.cz/", "official_league"),
    ("https://www.transfermarkt.com/x", "statistical_provider"),
    ("https://fbref.com/en/comps/", "statistical_provider"),
    ("https://www.idnes.cz/fotbal", "major_news"),
    ("https://sport.idnes.cz/clanek", "major_news"),   # subdoména
    ("https://m.sport.cz/x", "major_news"),            # subdoména
    ("https://www.sparta.cz/", "official_club"),
    ("https://random-blog.example/x", "unknown"),
])
def test_source_type(reg, url, expected):
    assert reg.get_source_type(url) == expected


def test_authority_ordering(reg):
    assert reg.get_authority("https://www.fotbal.cz/") > reg.get_authority("https://www.idnes.cz/")
    assert reg.get_authority("https://www.idnes.cz/") > reg.get_authority("https://livesport.cz/")
    assert reg.get_authority("https://livesport.cz/") > reg.get_authority("https://random-blog.example/")


def test_unrelated_suffix_is_not_matched(reg):
    # "evilidnes.cz" nesmí zdědit důvěryhodnost "idnes.cz"
    assert reg.get_source_type("https://evilidnes.cz/") == "unknown"
