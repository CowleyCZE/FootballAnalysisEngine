from typing import Dict, Any, Optional

class SplitsEngine:
    @staticmethod
    def calculate_halves_split(home_ht: Optional[int], away_ht: Optional[int], home_ft: Optional[int], away_ft: Optional[int]) -> Dict[str, Any]:
        if None in (home_ht, away_ht, home_ft, away_ft):
            return {"ht": None, "st": None, "valid": False}
        
        st_home = home_ft - home_ht
        st_away = away_ft - away_ht

        return {
            "ht": {"home_goals": home_ht, "away_goals": away_ht},
            "st": {"home_goals": st_home, "away_goals": st_away},
            "valid": True
        }