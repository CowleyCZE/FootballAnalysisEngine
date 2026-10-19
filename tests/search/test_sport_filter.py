from app.search.models import SearchResult
from app.search.sport_filter import is_football_content, filter_sports_results

def test_sport_filter_accepts_football():
    res = SearchResult(url="https://bbc.com/sport/football/123", title="Arsenal vs Chelsea preview", content="Team news and starting lineups for the Premier League derby match.")
    assert is_football_content(res) is True

def test_sport_filter_rejects_non_football():
    res = SearchResult(url="https://espn.com/nba/story/_/id/123", title="Lakers vs Celtics NBA Finals", content="LeBron James scored 35 points in basketball game.")
    assert is_football_content(res) is False
    filtered = filter_sports_results([res])
    assert len(filtered) == 0
