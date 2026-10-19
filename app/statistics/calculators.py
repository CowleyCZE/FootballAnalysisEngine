import statistics
from typing import List, Optional, Tuple

class StatisticsCalculator:
    @staticmethod
    def calculate_result(home_goals: int, away_goals: int, is_home: bool) -> Tuple[str, int]:
        if home_goals == away_goals:
            return "D", 1
        if is_home:
            return ("W", 3) if home_goals > away_goals else ("L", 0)
        else:
            return ("W", 3) if away_goals > home_goals else ("L", 0)

    @staticmethod
    def calculate_average(values: List[Optional[float]]) -> Optional[float]:
        valid_vals = [v for v in values if v is not None]
        if not valid_vals:
            return None
        return sum(valid_vals) / len(valid_vals)

    @staticmethod
    def calculate_median(values: List[Optional[float]]) -> Optional[float]:
        valid_vals = [v for v in values if v is not None]
        if not valid_vals:
            return None
        return float(statistics.median(valid_vals))