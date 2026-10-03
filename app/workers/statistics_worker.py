from typing import Any, Dict

from app.statistics.engine import StatisticalEngine


class StatisticsWorker:
    @staticmethod
    def execute(payload: Dict[str, Any]) -> Dict[str, Any]:
        required = ("match_id", "run_db_id", "home_team_id", "away_team_id", "cutoff_datetime")
        missing = [key for key in required if payload.get(key) is None]
        if missing:
            raise ValueError(f"STATISTICS job missing fields: {', '.join(missing)}")

        engine = StatisticalEngine()
        return engine.run_match_statistics(
            match_id=int(payload["match_id"]),
            run_id=int(payload["run_db_id"]),
            home_team_id=int(payload["home_team_id"]),
            away_team_id=int(payload["away_team_id"]),
            cutoff_datetime=str(payload["cutoff_datetime"]),
        )
