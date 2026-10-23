from app.search.models import SearchResult
from app.search.sport_filter import is_blocked_url, is_football_content


def test_blocked_urls_from_real_run():
    for url in (
        "https://www.eliteprospects.com/team/162/hc-slavia-praha/transfers",
        "https://cs.wikipedia.org/wiki/HC_Slavia_Praha",
        "https://cs.wikipedia.org/wiki/Kategorie:Fotbalisté_SK_Slavia_Praha",
        "https://www.idatabaze.cz/katalog/zdravi/traumatologicke-ambulance/jablonec-nad-nisou",
    ):
        assert is_blocked_url(url), url


def test_football_urls_not_blocked():
    assert not is_blocked_url("https://sempremilan.com/uel-preview-slavia-praha-vs-ac-milan")
    res = SearchResult(title="Slavia preview", content="football match goal", url="https://sports.yahoo.com/articles/preview-tottenham-vs-slavia-praha.html")
    assert is_football_content(res)
