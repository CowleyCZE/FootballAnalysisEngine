from typing import List, Dict, Any, Optional
from app.statistics.calculators import StatisticsCalculator

class AggregateEngine:
    @staticmethod
    def calculate_metric_aggregate(values: List[Optional[float]]) -> Dict[str, Any]:
        valid_vals = [v for v in values if v is not None]
        total_samples = len(values)
        valid_samples = len(valid_vals)
        
        coverage = (valid_samples / total_samples) if total_samples > 0 else 0.0

        return {
            "total_samples": total_samples,
            "valid_samples": valid_samples,
            "coverage": coverage,
            "average": StatisticsCalculator.calculate_average(values),
            "median": StatisticsCalculator.calculate_median(values)
        }