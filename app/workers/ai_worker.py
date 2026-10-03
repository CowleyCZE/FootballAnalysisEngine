from typing import Dict, Any

class AIWorker:
    @staticmethod
    def execute(payload: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "conclusion": "Tým vyhrál 6 z posledních 10 zápasů.",
            "key_factors": [
                {"factor": "Klíčový útočník je v dobré formě.", "evidence_ids": [1]}
            ]
        }
