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

        # SearchEngine supplies the primary relevance signal. SourceSelector
        # combines it with source authority before applying domain limits.
        # Ranking must happen before the quota so weak early results cannot
        # consume a domain's available slots.
        for res in search_results:
            raw_url = res.get("url", "")
            url = self.normalize_url(raw_url)
            if not url:
                continue

            info = self.registry.get_domain_info(url)
            score = self._calculate_score(info["authority"], res)
            publisher_id = self.registry.get_publisher_id(url) if hasattr(self.registry, "get_publisher_id") else info["domain"]

            candidate = {
                "url": url,
                "domain": info["domain"],
                "publisher_id": publisher_id,
                "source_type": info["source_type"],
                "score": score,
                "search_relevance": res.get("relevance", 0),
                "title": res.get("title", ""),
                "snippet": res.get("content", "")
            }
            candidates.append(candidate)

        candidates.sort(key=lambda x: x["score"], reverse=True)

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
        try:
            search_relevance = max(0.0, min(100.0, float(res.get("relevance", 0) or 0)))
        except (TypeError, ValueError):
            search_relevance = 0.0

        title_signal = 0.2 if res.get("title") else 0.0
        authority_signal = max(0.0, min(1.0, float(authority or 0.0)))

        # Keep the unified SearchEngine relevance dominant while preserving
        # the research-layer authority signal and a small title-quality signal.
        return round(
            0.6 * (search_relevance / 100.0)
            + 0.3 * authority_signal
            + 0.1 * title_signal,
            4,
        )
