from typing import List, Optional
from app.search.models import SearchResult

NON_FOOTBALL_KEYWORDS = {
    "basketball", "nba", "euroleague", "tennis", "atp", "wta", "grand slam",
    "ice hockey", "hockey", "nhl", "khl", "baseball", "mlb", "cricket",
    "rugby", "golf", "f1", "formula 1", "motogp", "volleyball", "handball",
    "badminton", "table tennis", "mma", "ufc", "boxing", "nfl", "american football",
    "snooker", "darts", "poker", "hokej", "hokejov", "lední hokej"
}

FOOTBALL_KEYWORDS = {
    "football", "soccer", "match", "league", "stadium", "cup", "derby",
    "striker", "midfielder", "defender", "goalkeeper", "manager", "transfer",
    "goal", "penalty", "corner", "offside", "fixture", "tactics", "champions league",
    "europa league", "premier league", "la liga", "serie a", "bundesliga", "substitute"
}


# Zjevně nefotbalové / neinformativní URL (hokej, wiki kategorie, katalogy firem a služeb).
_BLOCKED_URL_PARTS = (
    "eliteprospects.com", "/hc-", "/hc_", "hokej", "hockey", "/nhl", "/khl",
    "/kategorie:", "/category:", "special:", "/katalog/", "traumatolog",
    "cycling", "cyklist", "cyklo", "velodrom", "triathlon",
)


# TODO 11.20-a: šumové domény z měření produkční DB (vstupenky, fanshopy, streamy,
# Football Manager blog, obsahové farmy bez data publikace). Shoda na celou doménu/subdoménu.
NOISE_DOMAINS = (
    "livefootballtickets.com", "kooralivefree.com", "footballmanagerstory.com",
    "sportsdunia.com", "footballuser.com", "futbor.com", "skorjet.net",
)
# Štítky hostitele (první část domény) typické pro e-shopy a prodej vstupenek.
NOISE_HOST_LABEL_PREFIXES = ("fanshop", "eshop", "e-shop", "shop", "tickets", "ticket", "vstupenky")
# Podřetězce hostitele pro prodej vstupenek (např. livefootballtickets.com).
NOISE_HOST_PARTS = ("tickets", "vstupenky")


def is_noise_domain(url: str) -> bool:
    from urllib.parse import urlparse

    raw = (url or "").strip()
    host = (urlparse(raw if "//" in raw else "//" + raw).hostname or "").lower()
    if not host:
        return False
    if any(host == d or host.endswith("." + d) for d in NOISE_DOMAINS):
        return True
    if any(part in host for part in NOISE_HOST_PARTS):
        return True
    labels = host.split(".")
    # Jen subdoménové štítky (fanshop.slavia.cz); samotný „shop“ jako registrovaná doména se neřeší.
    return any(label.startswith(NOISE_HOST_LABEL_PREFIXES) for label in labels[:-2])


def is_blocked_url(url: str) -> bool:
    lowered = (url or "").lower()
    if is_noise_domain(lowered):
        return True
    return any(part in lowered for part in _BLOCKED_URL_PARTS)


def is_football_content(result: SearchResult) -> bool:
    if is_blocked_url(getattr(result, "url", "") or ""):
        return False
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


def is_match_relevant(
    result: SearchResult,
    home_team: Optional[str] = None,
    away_team: Optional[str] = None,
    competition: Optional[str] = None
) -> bool:
    if not is_football_content(result):
        return False

    text = f"{result.title} {result.content}".lower()

    ht_match = True
    if home_team and home_team.strip():
        ht_lower = home_team.lower().strip()
        ht_parts = [p for p in ht_lower.split() if len(p) > 3 and p not in {"club", "town", "city", "real", "fc", "fk", "sc"}]
        ht_match = ht_lower in text or any(p in text for p in ht_parts)

    at_match = True
    if away_team and away_team.strip():
        at_lower = away_team.lower().strip()
        at_parts = [p for p in at_lower.split() if len(p) > 3 and p not in {"club", "town", "city", "real", "fc", "fk", "sc"}]
        at_match = at_lower in text or any(p in text for p in at_parts)

    if home_team and away_team:
        if not (ht_match or at_match):
            return False

    return True


def filter_sports_results(results: List[SearchResult]) -> List[SearchResult]:
    return [r for r in results if is_football_content(r)]


def filter_sports_and_match_results(
    results: List[SearchResult],
    home_team: Optional[str] = None,
    away_team: Optional[str] = None,
    competition: Optional[str] = None
) -> List[SearchResult]:
    return [r for r in results if is_match_relevant(r, home_team, away_team, competition)]
