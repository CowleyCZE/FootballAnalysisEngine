from typing import Optional, Dict, Any

class XGModule:
    @staticmethod
    def calculate_xg_metrics(home_xg: Optional[float], away_xg: Optional[float]) -> Dict[str, Any]:
        if home_xg is None or away_xg is None:
            return {"xg_diff": None, "valid": False}
        return {
            "home_xg": home_xg,
            "away_xg": away_xg,
            "xg_diff": round(home_xg - away_xg, 2),
            "valid": True
        }