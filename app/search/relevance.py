def calculate_relevance(
    result,
    team: str = "",
    topic_terms: list[str] | None = None,
    source_priority: int = 0,
    source_authority: float = 0.2,
) -> int:
    topic_terms = topic_terms or []
    title = (getattr(result, "title", "") or "").lower()
    url = (getattr(result, "url", "") or "").lower()
    content = (getattr(result, "content", "") or "").lower()
    team_lower = (team or "").lower()

    score = 0
    if team_lower:
        if team_lower in title:
            score += 30
        if team_lower in url:
            score += 20

    for term in topic_terms:
        term_lower = (term or "").lower()
        if not term_lower:
            continue
        if term_lower in title:
            score += 15
        elif term_lower in content:
            score += 10

    try:
        priority = max(0, int(source_priority or 0))
    except (TypeError, ValueError):
        priority = 0

    try:
        authority = float(source_authority)
    except (TypeError, ValueError):
        authority = 0.2

    score += min(priority // 10, 20)
    score += round(max(0.0, min(1.0, authority)) * 20)
    return score
