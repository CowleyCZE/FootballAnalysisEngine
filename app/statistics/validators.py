from typing import List, Tuple
from app.statistics.models import MatchStatistics

class StatisticsValidator:
    def validate(self, stats: MatchStatistics) -> Tuple[bool, List[str]]:
        errors: List[str] = []

        # 1. Záporné hodnoty
        numeric_fields = [
            ("home_goals", stats.home_goals), ("away_goals", stats.away_goals),
            ("home_shots", stats.home_shots), ("away_shots", stats.away_shots),
            ("home_shots_on_target", stats.home_shots_on_target),
            ("away_shots_on_target", stats.away_shots_on_target),
            ("home_corners", stats.home_corners), ("away_corners", stats.away_corners),
            ("home_yellow_cards", stats.home_yellow_cards), ("away_yellow_cards", stats.away_yellow_cards),
            ("home_red_cards", stats.home_red_cards), ("away_red_cards", stats.away_red_cards),
        ]

        for field_name, val in numeric_fields:
            if val is not None and val < 0:
                errors.append(f"Záporná hodnota v poli {field_name}: {val}")

        # 2. Logická kontrola: Střely na branku <= Střely celkem
        if stats.home_shots is not None and stats.home_shots_on_target is not None:
            if stats.home_shots_on_target > stats.home_shots:
                errors.append(f"Domácí SOT ({stats.home_shots_on_target}) > Total shots ({stats.home_shots})")

        if stats.away_shots is not None and stats.away_shots_on_target is not None:
            if stats.away_shots_on_target > stats.away_shots:
                errors.append(f"Hosté SOT ({stats.away_shots_on_target}) > Total shots ({stats.away_shots})")

        # 3. Kontrola držení míče (0 - 100 %)
        if stats.home_possession is not None:
            if not (0 <= stats.home_possession <= 100):
                errors.append(f"Neplatné držení míče domácích: {stats.home_possession}%")

        if stats.away_possession is not None:
            if not (0 <= stats.away_possession <= 100):
                errors.append(f"Neplatné držení míče hostů: {stats.away_possession}%")

        # Kontrola součtu držení míče s tolerancí ±2 % (kvůli zaokrouhlování)
        if stats.home_possession is not None and stats.away_possession is not None:
            total_poss = stats.home_possession + stats.away_possession
            if not (98.0 <= total_poss <= 102.0):
                errors.append(f"Součet držení míče mimo toleranci 100±2%: {total_poss}%")

        is_valid = len(errors) == 0
        return is_valid, errors