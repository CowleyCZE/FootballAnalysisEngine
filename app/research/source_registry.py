from __future__ import annotations

from app.search.source_registry import SearchSourceRegistry


class SourceRegistry(SearchSourceRegistry):
    """Backward-compatible Research-layer facade over the unified registry."""

    def get_domain_info(self, url: str) -> dict:
        return self.get_info(url)
