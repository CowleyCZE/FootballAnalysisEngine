import yaml
from typing import Dict, Any

class SourcePolicy:
    def __init__(self, config_path: str = "config/research_strategy.yaml"):
        self.strategies = self._load_config(config_path)

    def _load_config(self, path: str) -> Dict[str, Any]:
        try:
            with open(path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        except Exception:
            return {}

    def get_strategy(self, domain: str) -> Dict[str, Any]:
        return self.strategies.get(domain, self.strategies.get("DEFAULT", {
            "strategy": "BASIC",
            "min_sources": 1,
            "min_independent_sources": 1,
            "max_queries": 4
        }))
