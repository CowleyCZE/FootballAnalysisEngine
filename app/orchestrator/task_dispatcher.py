from typing import List, Dict, Any, Optional

class TaskDispatcher:
    def __init__(self):
        # Konfigurace možností workerů
        self.workers = {
            "notebook": {
                "capabilities": ["http_fetch", "playwright", "parse", "statistics", "browser"],
                "max_concurrency": 4,
                "status": "ONLINE"
            },
            "note9": {
                "capabilities": ["http_fetch", "simple_parse"],
                "max_concurrency": 2,
                "status": "ONLINE"
            }
        }

    def set_worker_status(self, worker_id: str, status: str):
        if worker_id in self.workers:
            self.workers[worker_id]["status"] = status

    def select_worker(self, required_capabilities: List[str]) -> Optional[str]:
        for worker_id, info in self.workers.items():
            if info["status"] != "ONLINE":
                continue
            
            # Kontrola, zda worker zvládne všechny požadované vlastnosti
            can_handle = all(cap in info["capabilities"] for cap in required_capabilities)
            if can_handle:
                return worker_id
        return None