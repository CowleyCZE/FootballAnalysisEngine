from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
from typing import List, Dict, Any
from app.research.source_registry import SourceRegistry


class SourceSelector:
    def __init__(self, registry: SourceRegistry, max_per_domain: int = 3):
        self.registry = registry
        self.max_per_domain = max_per_domain

    def normalize_url(self, url: str) -> str:
        parsed = urlparse(url)
        if parsed.scheme not in ('http', 'https'):
            return ""

        query_params = parse_qs(parsed.query)
        filtered_params = {k: v for k, v in query_params.items() if not k.startswith('utm_')}
        clean_query = urlencode(filtered_params, doseq=True)

        return urlunparse((
            parsed.scheme,
            parsed.netloc.lower(),
            parsed.path.rstrip('/'),
            parsed.params,
            clean_query,
            ''
        ))

    def select_candidates(self, search_results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        candidates = []

        # SearchEngine already performs the authoritative relevance ranking.
        # Recalculate only the research-layer policy score here, then sort
        # BEFORE applying max_per_domain. This prevents low-quality early
        # results from consuming a domain's quota and hiding better sources.
        for res in search_results:
            raw_url = res.get("url", "")
            url = self.normalize_url(raw_url)
            if not url:
                continue

            info = self.registry.get_domain_info(url)
            score = self._calculate_score(info["authority"], res)

            candidate = {
                "url": url,
                "domain": info["domain"],
                "source_type": info["source_type"],
                "score": score,
                "search_relevance": res.get("relevance", 0),
                "title": res.get("title", ""),
                "snippet": res.get("content", "")
            }
            candidates.append(candidate)

        candidates.sort(
            key=lambda x: (
                x["score"],
                x.get("search_relevance", 0),
            ),
            reverse=True,
        )

        domain_counts: Dict[str, int] = {}
        selected = []
        for candidate in candidates:
            domain = candidate["domain"]
            if domain_counts.get(domain, 0) >= self.max_per_domain:
                continue
            selected.append(candidate)
            domain_counts[domain] = domain_counts.get(domain, 0) + 1

        return selected

    def _calculate_score(self, authority: float, res: Dict[str, Any]) -> float:
        relevance = 0.5
        if res.get("title"):
            relevance += 0.2
        return round(0.6 * authority + 0.4 * relevance, 2)
