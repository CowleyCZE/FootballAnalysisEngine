import asyncio
from app.search.searxng_client import SearXNGClient
from app.search.query_builder import build_queries
from app.search.normalizer import normalize_searx_result
from app.search.deduplicator import deduplicate
from app.search.relevance import calculate_relevance

async def main():
    team = "Sparta Praha"
    topics = ["injuries"]
    print(f"=== SOURCE ENGINE TEST ===")
    print(f"Tým: {team}, Téma: {topics}\n")

    client = SearXNGClient("http://127.0.0.1:8080")
    queries = build_queries(team, topics)
    print(f"Vygenerované dotazy ({len(queries)}): {[q.query for q in queries]}")

    all_results = []
    for q in queries:
        try:
            raw = await client.search(q.query, language=q.language)
            items = raw.get("results", [])
            for item in items:
                all_results.append(normalize_searx_result(item))
        except Exception as e:
            print(f"Chyba při vyhledávání '{q.query}': {e}")

    print(f"Nalezeno celkem výsledků: {len(all_results)}")
    
    # Deduplikace
    unique_results = deduplicate(all_results)
    print(f"Po deduplikaci: {len(unique_results)}")

    # Ohodnocení relevance
    for r in unique_results:
        r.score = calculate_relevance(r, team, ["zranění", "absence", "injury"])

    sorted_results = sorted(unique_results, key=lambda x: x.score, reverse=True)

    print("\n--- TOP 5 NEJRELEVANTNĚJŠÍCH VÝSLEDKŮ ---")
    for r in sorted_results[:5]:
        print(f"[{r.score} bodů] {r.title}\n URL: {r.url}\n")

if __name__ == "__main__":
    asyncio.run(main())
