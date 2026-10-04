from __future__ import annotations

import os
from urllib.parse import urlparse
from typing import Any

import yaml


class SearchSourceRegistry:
    """Single source-of-truth registry for source type and authority."""

    DEFAULT_TYPES = {
        "official_club": 1.0,
        "official_league": 1.0,
        "statistical_provider": 0.9,
        "major_news": 0.8,
        "aggregator": 0.5,
        "unknown": 0.2,
    }

    def __init__(self, config_path: str = "config/source_registry.yaml"):
        self.config_path = config_path
        self.config = self._load_config(config_path)
        self.source_types = self.config.get("source_types", self.DEFAULT_TYPES)
        self.domains = self.config.get("domains", {})

    @staticmethod
    def _load_config(path: str) -> dict[str, Any]:
        try:
            with open(path, "r", encoding="utf-8") as handle:
                return yaml.safe_load(handle) or {}
        except (OSError, yaml.YAMLError):
            return {}

    def get_info(self, url: str) -> dict[str, Any]:
        domain = urlparse(url).netloc.lower()
        if domain.startswith("www."):
            domain = domain[4:]

        domain_cfg = self.domains.get(domain, {})
        source_type = domain_cfg.get("type", "unknown")
        type_cfg = self.source_types.get(source_type, {})

        try:
            authority = float(type_cfg.get("authority", 0.2))
        except (TypeError, ValueError):
            authority = 0.2

        authority = max(0.0, min(1.0, authority))
        return {
            "domain": domain,
            "source_type": source_type,
            "authority": authority,
        }

    def get_domain_info(self, url: str) -> dict[str, Any]:
        """Compatibility alias for the former ResearchSourceRegistry API."""
        return self.get_info(url)
