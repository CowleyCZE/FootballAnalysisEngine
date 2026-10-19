import yaml
from pathlib import Path
from typing import Dict, Any

class PipelineConfig:
    @staticmethod
    def load(config_path: str = "config/pipeline.yaml") -> Dict[str, Any]:
        path = Path(config_path)
        if not path.exists():
            return {
                "orchestrator": {
                    "enabled": True, "poll_interval": 2, "max_parallel_jobs": 4,
                    "default_max_attempts": 3, "audit_max_cycles": 3,
                    "worker_timeout": 120, "job_timeout": 900, "recovery_enabled": True
                },
                "workers": {"max_search": 4, "max_crawler": 3, "max_ai": 1}
            }
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
