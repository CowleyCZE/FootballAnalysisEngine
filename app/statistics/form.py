from typing import List, Dict, Any
from app.statistics.calculators import StatisticsCalculator

class FormEngine:
    @staticmethod
    def calculate_form(matches_data: List[Dict[str, Any]], team_id: int, last_n: int = 5) -> Dict[str, Any]:
        recent_matches = matches_data[:last_n]
        
        results = []
        points = 0
        gf = 0
        ga = 0
        valid_count = 0

        for m in recent_matches:
            is_home = (m["home_team_id"] == team_id)
            h_goals = m.get("home_goals")
            a_goals = m.get("away_goals")

            if h_goals is None or a_goals is None:
                continue

            res, pts = StatisticsCalculator.calculate_result(h_goals, a_goals, is_home)
            results.append(res)
            points += pts
            
            if is_home:
                gf += h_goals
                ga += a_goals
            else:
                gf += a_goals
                ga += h_goals
            
            valid_count += 1

        return {
            "form_string": "-".join(results),
            "points": points,
            "max_points": valid_count * 3,
            "sample_size": valid_count,
            "gf": gf,
            "ga": ga,
            "gd": gf - ga,
            "gf_avg": (gf / valid_count) if valid_count > 0 else None,
            "ga_avg": (ga / valid_count) if valid_count > 0 else None
        }