def calculate_relevance(result, team: str, topic_terms: list[str], source_priority: int = 0) -> int:
    score = 0
    title = result.title.lower()
    url = result.url.lower()
    content = result.content.lower()
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

    score += min(source_priority // 10, 20)
    return score