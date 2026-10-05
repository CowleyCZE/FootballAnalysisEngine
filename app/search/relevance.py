from datetime import datetime
from typing import Optional

def calculate_relevance(
    result,
    team: str,
    topic_terms: list[str],
    source_priority: int = 0,
    source_authority: float = 0.0,
    data_cutoff_at: Optional[datetime] = None
) -> float:
    score = 0.0
    title = result.title.lower()
    url = result.url.lower()
    content = result.content.lower()
    team_lower = team.lower()

    if team_lower in title:
        score += 30.0
    if team_lower in url:
        score += 20.0

    for term in topic_terms:
        term_lower = term.lower()
        if term_lower in title:
            score += 15.0
        elif term_lower in content:
            score += 10.0

    score += min(source_priority // 10, 20)

    # Freshness calculation
    if data_cutoff_at and getattr(result, "published_at", None):
        try:
            pub_date = datetime.fromisoformat(str(result.published_at))
            if pub_date > data_cutoff_at:
                # Penalty for post-cutoff items if not filtered out
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