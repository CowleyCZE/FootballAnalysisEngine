from typing import List
from app.search.models import SearchResult

NON_FOOTBALL_KEYWORDS = {
    "basketball", "nba", "tennis", "hockey", "nhl", "baseball", "mlb",
    "cricket", "rugby", "golf", "f1", "formula 1", "volleyball", "handball",
    "badminton", "table tennis", "mma", "ufc", "boxing", "nfl", "american football"
}

FOOTBALL_KEYWORDS = {
    "football", "soccer", "match", "league", "stadium", "cup", "derby",
    "striker", "midfielder", "defender", "goalkeeper", "manager", "transfer",
    "goal", "penalty", "corner", "offside", "fixture", "tactics"
}

def is_football_content(result: SearchResult) -> bool:
    text = f"{result.title} {result.content}".lower()
    
    if result.category and result.category.lower() not in ["general", "news", "sports", "sport"]:
        return False
        
    non_football_count = sum(1 for kw in NON_FOOTBALL_KEYWORDS if kw in text)
    football_count = sum(1 for kw in FOOTBALL_KEYWORDS if kw in text)
    
    if non_football_count > 0 and football_count == 0:
        return False
        
    if non_football_count > football_count + 1:
        return False
        
    return True

def filter_sports_results(results: List[SearchResult]) -> List[SearchResult]:
    return [r for r in results if is_football_content(r)]
