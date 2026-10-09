from datetime import datetime
from typing import Optional, List
from urllib.parse import urlparse

YOUTH_RESERVE_KEYWORDS = {
    "u15", "u16", "u17", "u18", "u19", "u21", "u23",
    "under-15", "under-17", "under-18", "under-19", "under-21", "under-23",
    "youth", "dorost", "juniors", "b team", "reserves", "rezerva", "u-19", "u-21"
}

AMBIGUOUS_DOMAINS = {
    "youtube.com", "m.youtube.com", "tiktok.com", "instagram.com", "facebook.com", "x.com", "twitter.com"
}


def calculate_identity_confidence(
    result,
    home_team: Optional[str] = None,
    away_team: Optional[str] = None,
    competition: Optional[str] = None,
    scheduled_at: Optional[datetime] = None
) -> float:
    text = f"{getattr(result, 'title', '')} {getattr(result, 'content', '')}".lower()
    confidence = 0.0

    # Team presence checks
    if home_team and home_team.strip():
        ht_lower = home_team.lower().strip()
        if ht_lower in text:
            confidence += 0.35
        else:
            ht_parts = [p for p in ht_lower.split() if len(p) > 3 and p not in {"club", "real", "fc", "fk", "sc"}]
            if any(p in text for p in ht_parts):
                confidence += 0.25

    if away_team and away_team.strip():
        at_lower = away_team.lower().strip()
        if at_lower in text:
            confidence += 0.35
        else:
            at_parts = [p for p in at_lower.split() if len(p) > 3 and p not in {"club", "real", "fc", "fk", "sc"}]
            if any(p in text for p in at_parts):
                confidence += 0.25

    if not home_team and not away_team:
        confidence += 0.5

    # Competition check
    if competition and competition.strip():
        comp_lower = competition.lower().strip()
        if comp_lower in text:
            confidence += 0.2

    # Date / Year check
    if scheduled_at:
        year_str = str(scheduled_at.year)
        if year_str in text:
            confidence += 0.1

    return min(1.0, confidence)


def calculate_relevance(
    result,
    team: str = "",
    topic_terms: Optional[List[str]] = None,
    source_priority: int = 0,
    source_authority: float = 0.0,
    data_cutoff_at: Optional[datetime] = None,
    home_team: Optional[str] = None,
    away_team: Optional[str] = None,
    competition: Optional[str] = None
) -> float:
    score = 0.0
    title = getattr(result, "title", "").lower()
    url = getattr(result, "url", "").lower()
    content = getattr(result, "content", "").lower()
    text = f"{title} {content}"

    # Authority bonus
    score += source_authority * 25.0

    # Main team / query team match
    target_team = team or home_team or ""
    if target_team and target_team.lower() in title:
        score += 30.0
    elif target_team and target_team.lower() in url:
        score += 20.0

    if away_team and away_team.lower() in title:
        score += 25.0

    # Youth / reserve penalty
    if any(kw in text for kw in YOUTH_RESERVE_KEYWORDS):
        score -= 80.0

    # Ambiguity penalty for video/social platforms or generic content
    domain = ""
    try:
        domain = urlparse(url).netloc.lower()
        if domain.startswith("www."):
            domain = domain[4:]
    except Exception:
        pass

    if domain in AMBIGUOUS_DOMAINS:
        score -= 40.0

    # Topic terms match
    for term in (topic_terms or []):
        term_lower = term.lower()
        if term_lower in title:
            score += 15.0
        elif term_lower in content:
            score += 10.0

    score += min(source_priority // 10, 20)

    # Freshness / Cutoff calculation
    if data_cutoff_at and getattr(result, "published_at", None):
        try:
            pub_date = datetime.fromisoformat(str(result.published_at).replace("Z", "+00:00"))
            if pub_date.tzinfo is None and getattr(data_cutoff_at, "tzinfo", None) is not None:
                pub_date = pub_date.replace(tzinfo=data_cutoff_at.tzinfo)
            elif data_cutoff_at.tzinfo is None and pub_date.tzinfo is not None:
                data_cutoff_at = data_cutoff_at.replace(tzinfo=pub_date.tzinfo)
            if pub_date > data_cutoff_at:
                score -= 100.0
            else:
                days_diff = (data_cutoff_at - pub_date).days
                if days_diff <= 7:
                    score += 20.0
                elif days_diff <= 30:
                    score += 10.0
                elif days_diff <= 90:
                    score += 5.0
        except Exception:
            pass

    return max(0.0, score)
