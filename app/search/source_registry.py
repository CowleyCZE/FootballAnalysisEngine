from __future__ import annotations

import logging
import os
from urllib.parse import urlparse
import yaml

logger = logging.getLogger(__name__)


class SearchSourceRegistry:
    DEFAULT_AUTHORITY = 0.2

    def __init__(self, config_path: str = "config/source_registry.yaml"):
        self.config_path = config_path
        self._source_types = {
            "official_club": 1.0,
            "official_league": 1.0,
            "statistical_provider": 0.9,
            "major_news": 0.8,
            "aggregator": 0.5,
            "unknown": 0.2,
        }
        self._domains = {}
        self.load_config(config_path)

    def load_config(self, config_path: str) -> None:
        if not os.path.exists(config_path):
            logger.warning("SourceRegistry YAML file not found: %s. Using default fallback configuration.", config_path)
            return
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}

            st = data.get("source_types", {})
            for name, cfg in st.items():
                if isinstance(cfg, dict) and "authority" in cfg:
                    self._source_types[name] = float(cfg["authority"])

            doms = data.get("domains", {})
            for domain, cfg in doms.items():
                if isinstance(cfg, dict):
                    self._domains[domain.lower()] = cfg.get("type", "unknown")
                elif isinstance(cfg, str):
                    self._domains[domain.lower()] = cfg
        except Exception as exc:
            logger.error("Failed to parse SourceRegistry configuration YAML at %s: %s", config_path, exc, exc_info=True)

    @property
    def DOMAINS(self) -> dict[str, str]:
        return self._domains

    @property
    def SOURCE_TYPES(self) -> dict[str, float]:
        return self._source_types

    def get_domain(self, url: str) -> str:
        try:
            domain = urlparse(url).netloc.lower()
        except Exception:
            return ""

        if domain.startswith("www."):
            domain = domain[4:]

        return domain

    def get_source_type(self, url: str) -> str:
        domain = self.get_domain(url)

        if domain in self._domains:
            return self._domains[domain]

        return "unknown"

    def get_publisher_id(self, url: str) -> str:
        """Stable publisher identity used for source-independence checks."""
        return self.get_domain(url)

    def get_authority(self, url: str) -> float:
        source_type = self.get_source_type(url)
        return self._source_types.get(
            source_type,
            self.DEFAULT_AUTHORITY,
        )

    def get_info(self, url: str) -> dict:
        domain = self.get_domain(url)
        source_type = self.get_source_type(url)
        authority = self._source_types.get(
            source_type,
            self.DEFAULT_AUTHORITY,
        )

        return {
            "domain": domain,
            "source_type": source_type,
            "authority": authority,
        }
