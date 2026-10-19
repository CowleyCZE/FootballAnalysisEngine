import sqlite3
from typing import Dict, Any, Optional, Mapping
from app.statistics.repository import StatisticsRepository
from app.statistics.validators import StatisticsValidator
from app.statistics.form import FormEngine
from app.statistics.aggregates import AggregateEngine
from app.statistics.models import MatchStatistics
from app.statistics.score_predictor import ExactScorePredictor
from app.statistics.research_context import ResearchContextMapper
from app.statistics.history_autofill import HistoryAutoFiller
import json

class StatisticalEngine:
    CALCULATION_VERSION = "1.0.0"

    def __init__(self, db_path: str = "database/football.db"):
        self.repo = StatisticsRepository(db_path)
        self.validator = StatisticsValidator()

    def run_match_statistics(self, match_id: int, run_id: int, home_team_id: int, away_team_id: int, cutoff_datetime: str,
                             home_context: Optional[Mapping[str, Any]] = None,
                             away_context: Optional[Mapping[str, Any]] = None,
                             match_context: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
        warnings = []
        errors = []

        # Research jobs may finish before STATISTICS. Reuse only validated
        # snapshots from this run/cutoff and let explicit caller values win.
        research_context = ResearchContextMapper.from_db(
            self.repo.db_path, match_id, run_id, cutoff_datetime
        )
        merged_home_context = {**research_context.get("home_context", {}), **dict(home_context or {})}
        merged_away_context = {**research_context.get("away_context", {}), **dict(away_context or {})}
        merged_match_context = {**research_context.get("match_context", {}), **dict(match_context or {})}
        
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
        home_matches = self.repo.get_team_recent_matches(home_team_id, cutoff_datetime=cutoff_datetime, limit=20)
        away_matches = self.repo.get_team_recent_matches(away_team_id, cutoff_datetime=cutoff_datetime, limit=20)
        h2h_matches = self.repo.get_head_to_head(home_team_id, away_team_id, cutoff_datetime=cutoff_datetime, limit=8)

        # A clean installation can discover and cache a public structured
        # history source before declaring the statistics phase incomplete.
        if len(home_matches) < 5 or len(away_matches) < 5:
            try:
                with sqlite3.connect(self.repo.db_path) as conn:
                    team_rows = conn.execute(
                        "SELECT id, name FROM teams WHERE id IN (?, ?)",
                        (home_team_id, away_team_id),
                    ).fetchall()
                    competition_row = conn.execute(
                        "SELECT COALESCE(c.name, m.competition, '') FROM matches m LEFT JOIN competitions c ON c.id=m.competition_id WHERE m.id=?",
                        (match_id,),
                    ).fetchone()
                competition = competition_row[0] if competition_row else ""
                auto_result = HistoryAutoFiller(db_path=self.repo.db_path).ensure(
                    home_team_id, away_team_id, competition, cutoff_datetime
                )
                if auto_result.get("imported"):
                    warnings.append(
                        f"Historie automaticky doplněna: {auto_result['imported']} zápasů ze zdroje {', '.join(auto_result.get('source') or [])}."
                    )
                warnings.extend(auto_result.get("warnings") or [])
                home_matches = self.repo.get_team_recent_matches(home_team_id, cutoff_datetime=cutoff_datetime, limit=20)
                away_matches = self.repo.get_team_recent_matches(away_team_id, cutoff_datetime=cutoff_datetime, limit=20)
                h2h_matches = self.repo.get_head_to_head(home_team_id, away_team_id, cutoff_datetime=cutoff_datetime, limit=8)
            except Exception as exc:
                warnings.append(f"Automatické doplnění historie selhalo: {exc}")

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
        away_xg_list = [m.get("away_xg") if m["away_team_id"] == away_team_id else m.get("home_xg") for m in away_matches]
        away_xg_agg = AggregateEngine.calculate_metric_aggregate(away_xg_list)

        home_cov = home_xg_agg.get("coverage", 0.0)
        away_cov = away_xg_agg.get("coverage", 0.0)

        if home_cov < 1.0:
            warnings.append(f"xG coverage pro domácí je {home_cov*100:.0f}%.")
        if away_cov < 1.0:
            warnings.append(f"xG coverage pro hosty je {away_cov*100:.0f}%.")

        total_sample = home_form["sample_size"] + away_form["sample_size"]
        if total_sample == 0:
            status = "INSUFFICIENT_DATA"
            warnings.append("Historie obou týmů chybí; použita je pouze neutrální ligová priorní predikce s velmi nízkou důvěrou.")
            warnings.append("Importujte historické výsledky příkazem: python scripts/import_history_csv.py --csv SOUBOR.csv --competition 'SOUTĚŽ'.")
        else:
            status = "COMPLETED"
            if home_cov == 0.0 and away_cov == 0.0:
                warnings.append("xG není dostupné; výpočet používá pouze výsledky a góly.")

        historical = {int(m["match_id"]): m for m in home_matches + away_matches}
        ordered_history = sorted(historical.values(), key=lambda m: str(m.get("scheduled_at") or ""), reverse=True)
        prediction = ExactScorePredictor.predict(
            ordered_history, home_team_id, away_team_id,
            h2h_rows=h2h_matches,
            home_context=merged_home_context,
            away_context=merged_away_context,
            match_context=merged_match_context,
        )
        if prediction and prediction.get("factors", {}).get("prior_only") and total_sample > 0:
            status = "INSUFFICIENT_DATA"
            warnings.append(
                "Historie je dostupná pouze pro jeden tým; výsledek používá degradovaný prior a má nízkou důvěru."
            )

        # 5. Uložení výsledných snapshotů pro domácí i hosty
        try:
            self.repo.save_snapshot(
                run_id=run_id,
                match_id=match_id,
                team_id=home_team_id,
                metric="form_points",
                value=float(home_form["points"]),
                sample_size=home_form["sample_size"],
                coverage=home_cov,
                data_cutoff_at=cutoff_datetime,
                calculation_version=self.CALCULATION_VERSION
            )
            self.repo.save_snapshot(
                run_id=run_id,
                match_id=match_id,
                team_id=away_team_id,
                metric="form_points",
                value=float(away_form["points"]),
                sample_size=away_form["sample_size"],
                coverage=away_cov,
                data_cutoff_at=cutoff_datetime,
                calculation_version=self.CALCULATION_VERSION
            )
        except (ValueError, sqlite3.IntegrityError) as exc:
            warnings.append(f"STATISTICS snapshot nebyl uložen: {exc}")

        if prediction:
            try:
                with sqlite3.connect(self.repo.db_path) as conn:
                    run_row = conn.execute("SELECT run_id FROM runs WHERE id=?", (int(run_id),)).fetchone()
                    if run_row:
                        conn.execute("""
                            INSERT INTO match_predictions(
                                match_id,run_id,data_cutoff_at,model_version,expected_home_goals,expected_away_goals,
                                predicted_home_goals,predicted_away_goals,home_win_probability,draw_probability,
                                away_win_probability,score_probabilities_json,sample_size
                            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                            ON CONFLICT(run_id) DO UPDATE SET
                                data_cutoff_at=excluded.data_cutoff_at, model_version=excluded.model_version,
                                expected_home_goals=excluded.expected_home_goals, expected_away_goals=excluded.expected_away_goals,
                                predicted_home_goals=excluded.predicted_home_goals, predicted_away_goals=excluded.predicted_away_goals,
                                home_win_probability=excluded.home_win_probability, draw_probability=excluded.draw_probability,
                                away_win_probability=excluded.away_win_probability,
                                score_probabilities_json=excluded.score_probabilities_json, sample_size=excluded.sample_size
                        """, (match_id, run_row[0], cutoff_datetime, prediction["model_version"], prediction["expected_home_goals"],
                              prediction["expected_away_goals"], prediction["predicted_home_goals"], prediction["predicted_away_goals"],
                              prediction["home_win_probability"], prediction["draw_probability"], prediction["away_win_probability"],
                              json.dumps(prediction["score_probabilities"]), prediction["sample_size"]))
            except sqlite3.Error as exc:
                warnings.append(f"Predikce přesného skóre nebyla uložena: {exc}")

        return {
            "match_id": match_id,
            "run_id": run_id,
            "status": status,
            "sample_size": total_sample,
            "coverage": min(home_cov, away_cov),
            "home_team": {"id": home_team_id, "form": home_form, "xg_aggregate": home_xg_agg},
            "away_team": {"id": away_team_id, "form": away_form, "xg_aggregate": away_xg_agg},
            "head_to_head": {"sample_size": len(h2h_matches)},
            "research_context": {
                "home": merged_home_context,
                "away": merged_away_context,
                "match": merged_match_context,
            },
            "prediction": prediction,
            "warnings": warnings,
            "errors": errors
        }
