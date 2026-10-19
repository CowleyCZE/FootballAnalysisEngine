import re
import hashlib
import yaml
from typing import List, Dict, Any
from app.research.models import ResearchTask

class QueryBuilder:
    def __init__(self, config_path: str = "config/research_queries.yaml"):
        self.config = self._load_config(config_path)

    def _load_config(self, path: str) -> Dict[str, Any]:
        try:
            with open(path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        except Exception:
            return {}

    def build_queries(self, task: ResearchTask) -> List[Dict[str, str]]:
        domain_templates = self.config.get(task.domain, {})
        queries = []

        context = {
            "home_team": task.home_team or "",
            "away_team": task.away_team or "",
            "competition": task.competition or "",
            "match_date": task.scheduled_at.strftime("%Y-%m-%d") if task.scheduled_at else "",
            "venue": task.venue or ""
        }

        for q_type, templates in domain_templates.items():
            for tpl in templates:
                try:
                    formatted = tpl.format(**context)
                    sanitized = self._sanitize_query(formatted)
                    if sanitized:
                        queries.append({
                            "query": sanitized,
                            "type": q_type.upper(),
                            "hash": self._hash_query(sanitized)
                        })
                except KeyError:
                    continue

        return self._deduplicate_queries(queries)

    def _sanitize_query(self, query: str) -> str:
        q = re.sub(r'\b(None|null|{}|\{\})\b', '', query, flags=re.IGNORECASE)
        q = re.sub(r'[^\w\s-]', ' ', q)
        q = ' '.join(q.split())
        return q if len(q) >= 3 else ""

    def _hash_query(self, query: str) -> str:
        return hashlib.sha256(query.lower().encode('utf-8')).hexdigest()

    def _deduplicate_queries(self, queries: List[Dict[str, str]]) -> List[Dict[str, str]]:
        seen = set()
        unique = []
        for q in queries:
            if q["hash"] not in seen:
                seen.add(q["hash"])
                unique.append(q)
        return unique
