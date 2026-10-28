from typing import Any, Dict

from app.statistics.engine import StatisticalEngine
from app.statistics.csv_data_sync import refresh_stale


class StatisticsWorker:
    @staticmethod
    def execute(payload: Dict[str, Any]) -> Dict[str, Any]:
        required = ("match_id", "run_db_id", "home_team_id", "away_team_id", "cutoff_datetime")
        missing = [key for key in required if payload.get(key) is None]
        if missing:
            raise ValueError(f"STATISTICS job missing fields: {', '.join(missing)}")

        db_path = payload.get("db_path", "database/football.db")
        try:
            csv_refresh = refresh_stale(db_path)
        except Exception as exc:
            # Refresh outages must not prevent a prediction from using the
            # already imported history; report the failure in its result.
            csv_refresh = {"status": "ERROR", "error": str(exc)}
        engine = StatisticalEngine(db_path=db_path)
        result = engine.run_match_statistics(
            match_id=int(payload["match_id"]),
            run_id=int(payload["run_db_id"]),
            home_team_id=int(payload["home_team_id"]),
            away_team_id=int(payload["away_team_id"]),
            cutoff_datetime=str(payload["cutoff_datetime"]),
        )
        if csv_refresh.get("status") == "ERROR" or any(item.get("status") == "ERROR" for item in csv_refresh.get("refreshed", [])):
            result.setdefault("warnings", []).append("Aktualizace soutěžních CSV selhala; predikce pokračovala s již uloženými daty.")
        result["csv_data_refresh"] = csv_refresh
        return result
