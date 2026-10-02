from app.search.models import QuerySpec

QUERY_TEMPLATES = {
    "injuries": [
        "{team} zranění",
        "{team} absence",
        "{team} sestava",
        "{team} injury update",
    ],
    "news": [
        "{team} novinky",
        "{team} před zápasem",
        "{team} team news",
    ],
}

def build_queries(team: str, topics: list[str]) -> list[QuerySpec]:
    queries = []
    for topic in topics:
        templates = QUERY_TEMPLATES.get(topic, [])
        for template in templates:
            queries.append(
                QuerySpec(
                    query=template.format(team=team),
                    reason=topic,
                    language="cs" if "zranění" in template or "sestava" in template else "en"
                )
            )
    return queries[:30]