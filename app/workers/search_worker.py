from typing import Dict, Any

class SearchWorker:
    @staticmethod
    def execute(payload: Dict[str, Any]) -> Dict[str, Any]:
        query = payload.get("query", "football match")
        return {
            "status": "completed",
            "results": [
                {"title": f"Result for {query}", "url": "https://example.com/match", "snippet": "Match preview and stats."}
            ]
        }
