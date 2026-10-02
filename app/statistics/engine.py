from typing import Dict, Any
from app.statistics.repository import StatisticsRepository
from app.statistics.validators import StatisticsValidator
from app.statistics.form import FormEngine
from app.statistics.aggregates import AggregateEngine
from app.statistics.models import MatchStatistics

class StatisticalEngine:
    CALCULATION_VERSION = "1.0.0"

    def __init__(self, db_path: str = "database/football.db"):
        self.repo = StatisticsRepository(db_path)
        self.validator = StatisticsValidator()

    def run_match_statistics(self, match_id: int, run_id: int, home_team_id: int, away_team_id: int, cutoff_datetime: str) -> Dict[str, Any]:
        warnings = []
        errors = []
        
        # 1. Načtení a validace cílových statistik
        match_stat_dict = self.repo.get_match_statistics(match_id)
        if match_stat_dict:
            # Převod dictu z DB na dataclass
            fields = MatchStatistics.__dataclass_fields__
            filtered_args = {k: v for k, v in match_stat_dict.items() if k in fields}
            stats_obj = MatchStatistics(**filtered_args)
            
            is_valid, val_errors = self.validator.validate(stats_obj)
            if not is_valid:
                errors.extend(val_errors)
                return {
                    "match_id": match_id,
                    "run_id": run_id,
                    "status": "INVALID_DATA",
                    "errors": errors,
                    "warnings": warnings
                }

        # 2. Načtení historie zápasů (před cutoff date)
        home_matches = self.repo.get_team_recent_matches(home_team_id, cutoff_datetime=cutoff_datetime, limit=5)
        away_matches = self.repo.get_team_recent_matches(away_team_id, cutoff_datetime=cutoff_datetime, limit=5)

        if len(home_matches) < 5:
            warnings.append(f"Domácí mají pouze {len(home_matches)} zápasů z 5 (INSUFFICIENT_SAMPLE).")
        if len(away_matches) < 5:
            warnings.append(f"Hosté mají pouze {len(away_matches)} zápasů z 5 (INSUFFICIENT_SAMPLE).")

        # 3. Výpočet formy
        home_form = FormEngine.calculate_form(home_matches, team_id=home_team_id, last_n=5)
        away_form = FormEngine.calculate_form(away_matches, team_id=away_team_id, last_n=5)

        # 4. Výpočet agregace a coverage xG
        home_xg_list = [m.get("home_xg") if m["home_team_id"] == home_team_id else m.get("away_xg") for m in home_matches]
        home_xg_agg = AggregateEngine.calculate_metric_aggregate(home_xg_list)

        if home_xg_agg["coverage"] < 1.0:
            warnings.append(f"xG coverage pro domácí je {home_xg_agg['coverage']*100:.0f}%.")

        # 5. Uložení výsledného snapshotu
        self.repo.save_snapshot(
            run_id=run_id,
            match_id=match_id,
            team_id=home_team_id,
            metric="form_points",
            value=float(home_form["points"]),
            sample_size=home_form["sample_size"],
            coverage=1.0,
            data_cutoff_at=cutoff_datetime,
            calculation_version=self.CALCULATION_VERSION
        )

        return {
            "match_id": match_id,
            "run_id": run_id,
            "status": "COMPLETED",
            "home_team": {"id": home_team_id, "form": home_form, "xg_aggregate": home_xg_agg},
            "away_team": {"id": away_team_id, "form": away_form},
            "warnings": warnings,
            "errors": errors
        }