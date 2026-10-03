from typing import Dict, Any

class StatisticsWorker:
    @staticmethod
    def execute(payload: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "wins": 6,
            "draws": 2,
            "losses": 2,
            "matches": 10
        }
