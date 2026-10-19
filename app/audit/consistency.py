from typing import Dict, Any, List

class ConsistencyChecker:
    @staticmethod
    def check_statistical_consistency(stats: Dict[str, Any], claims: List[Dict[str, Any]], analysis_dict: Dict[str, Any]) -> List[Dict[str, Any]]:
        issues = []
        
        # 1. Kontrola logického součtu statistik
        wins = stats.get("wins")
        draws = stats.get("draws")
        losses = stats.get("losses")
        total_matches = stats.get("matches")

        if wins is not None and draws is not None and losses is not None and total_matches is not None:
            if wins + draws + losses != total_matches:
                issues.append({
                    "type": "statistical_inconsistency",
                    "severity": "CRITICAL",
                    "description": f"Součet výher({wins}), remíz({draws}) a proher({losses}) neodpovídá celku({total_matches})",
                    "requires_research": False
                })

        # 2. Kontrola tvrzení AI oproti oficiálním statistikám
        conclusion = analysis_dict.get("conclusion", "").lower()
        if "vyhrál 7 z posledních 10" in conclusion and wins is not None and wins != 7:
            issues.append({
                "type": "statistical_contradiction",
                "severity": "CRITICAL",
                "description": f"AI uvádí 7 výher, ale statistická vrstva obsahuje {wins} výher",
                "requires_research": False
            })

        return issues
