from typing import Dict, Any
from app.statistics.models import MatchStatistics
from app.statistics.normalizer import SourceNormalizer

class StatisticExtractor:
    def extract_from_dict(self, match_id: int, raw_stats: Dict[str, Any]) -> Dict[str, Any]:
        normalizer = SourceNormalizer()
        
        stats = MatchStatistics(
            match_id=match_id,
            home_shots=normalizer.parse_int(raw_stats.get("home_shots")),
            away_shots=normalizer.parse_int(raw_stats.get("away_shots")),
            home_shots_on_target=normalizer.parse_int(raw_stats.get("home_shots_on_target")),
            away_shots_on_target=normalizer.parse_int(raw_stats.get("away_shots_on_target")),
            home_possession=normalizer.parse_float(raw_stats.get("home_possession")),
            away_possession=normalizer.parse_float(raw_stats.get("away_possession")),
            home_corners=normalizer.parse_int(raw_stats.get("home_corners")),
            away_corners=normalizer.parse_int(raw_stats.get("away_corners")),
            home_goals=normalizer.parse_int(raw_stats.get("home_goals")),
            away_goals=normalizer.parse_int(raw_stats.get("away_goals")),
            home_xg=normalizer.parse_float(raw_stats.get("home_xg")),
            away_xg=normalizer.parse_float(raw_stats.get("away_xg"))
        )
        
        evidence_chain = []
        for metric_name, raw_val in raw_stats.items():
            if raw_val is not None:
                evidence_chain.append({"metric": metric_name, "raw_value": str(raw_val)})
                
        return {
            "statistics": stats,
            "evidence_chain": evidence_chain
        }