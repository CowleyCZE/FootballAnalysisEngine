from __future__ import annotations


def calculate_relevance(
    result,
    team: str,
    topic_terms: list[str],
    source_priority: int = 0,
    source_authority: float = 0.0,
) -> int:
    score = 0

    title = (result.title or "").lower()
    url = (result.url or "").lower()
    content = (result.content or "").lower()
    team_lower = team.lower()

    if team_lower in title:
        score += 30

    if team_lower in url:
        score += 20

    for term in topic_terms:
        term_lower = term.lower()

        if term_lower in title:
            score += 15
        elif term_lower in content:
            score += 10

    score += min(max(source_priority, 0) // 10, 20)

    if source_authority:
        score += round(max(0.0, min(source_authority, 1.0)) * 20)

    return score
