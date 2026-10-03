import yaml
from urllib.parse import urlparse
from typing import Dict, Any

class SourceRegistry:
    def __init__(self, config_path: str = "config/source_registry.yaml"):
        self.config = self._load_config(config_path)
        self.source_types = self.config.get("source_types", {})
        self.domains = self.config.get("domains", {})

    def _load_config(self, path: str) -> Dict[str, Any]:
        try:
            with open(path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        except Exception:
            return {}

    def get_domain_info(self, url: str) -> Dict[str, Any]:
        domain = urlparse(url).netloc.lower()
        if domain.startswith("www."):
            domain = domain[4:]

        domain_cfg = self.domains.get(domain, {})
        stype = domain_cfg.get("type", "unknown")
        type_info = self.source_types.get(stype, {"authority": 0.2})

        return {
            "domain": domain,
            "source_type": stype,
            "authority": type_info.get("authority", 0.2)
        }
