"""Explainable exact-score prediction with form, venue, xG, H2H and context.

The predictor is deliberately deterministic and does not fabricate missing team
facts. If both histories are absent it may emit a clearly labelled neutral
league prior; all optional context values are bounded and reported in ``factors``.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Mapping, Optional, Tuple


class ExactScorePredictor:
    MODEL_VERSION = "poisson-context-v3"
    MAX_GOALS = 7

    @staticmethod
    def _weighted_mean(values: List[float], prior_mean: float = 1.25,
                       prior_weight: float = 3.0) -> Optional[float]:
        values = [float(v) for v in values if v is not None and math.isfinite(float(v))]
        if not values:
            return None
        weights = [math.exp(-0.14 * i) for i in range(len(values))]
        return (sum(v * w for v, w in zip(values, weights)) + prior_mean * prior_weight) / (sum(weights) + prior_weight)

    @staticmethod
    def _team_value(row: Mapping[str, Any], team_id: int) -> Tuple[float, float]:
        is_home = int(row["home_team_id"]) == int(team_id)
        goals = row.get("home_goals" if is_home else "away_goals")
        against = row.get("away_goals" if is_home else "home_goals")
        xg = row.get("home_xg" if is_home else "away_xg")
        xga = row.get("home_xga" if is_home else "away_xga")
        # Blend observed goals with xG, but use the available series when one is absent.
        attack = 0.65 * float(goals) + 0.35 * float(xg) if goals is not None and xg is not None else (float(xg) if xg is not None else float(goals))
        defence = 0.65 * float(against) + 0.35 * float(xga) if against is not None and xga is not None else (float(xga) if xga is not None else float(against))
        return attack, defence

    @staticmethod
    def _bounded(value: Any, low: float, high: float, default: float) -> float:
        try:
            value = float(value)
            return max(low, min(high, value)) if math.isfinite(value) else default
        except (TypeError, ValueError):
            return default

    @classmethod
    def _team_rates(cls, rows: List[Dict[str, Any]], team_id: int, venue: str) -> Optional[Tuple[float, float, int]]:
        all_rows = [r for r in rows if int(r.get("home_team_id")) == team_id or int(r.get("away_team_id")) == team_id]
        venue_rows = [r for r in all_rows if (venue == "home" and int(r.get("home_team_id")) == team_id) or (venue == "away" and int(r.get("away_team_id")) == team_id)]
        if not all_rows:
            return None
        # Venue split is useful only with enough observations; otherwise shrink toward all matches.
        all_values = [cls._team_value(r, team_id) for r in all_rows]
        all_attack = cls._weighted_mean([v[0] for v in all_values])
        all_defence = cls._weighted_mean([v[1] for v in all_values])
        split_values = [cls._team_value(r, team_id) for r in venue_rows]
        split_attack = cls._weighted_mean([v[0] for v in split_values]) if len(split_values) >= 3 else None
        split_defence = cls._weighted_mean([v[1] for v in split_values]) if len(split_values) >= 3 else None
        attack = 0.70 * split_attack + 0.30 * all_attack if split_attack is not None else all_attack
        defence = 0.70 * split_defence + 0.30 * all_defence if split_defence is not None else all_defence
        return attack, defence, len(all_rows)

    @classmethod
    def predict(
        cls,
        rows: List[Dict[str, Any]],
        home_team_id: int,
        away_team_id: int,
        *,
        h2h_rows: Optional[List[Dict[str, Any]]] = None,
        home_context: Optional[Mapping[str, Any]] = None,
        away_context: Optional[Mapping[str, Any]] = None,
        match_context: Optional[Mapping[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        home_rates = cls._team_rates(rows, home_team_id, "home")
        away_rates = cls._team_rates(rows, away_team_id, "away")
        prior_only = home_rates is None or away_rates is None
        if prior_only:
            # This is not a team fact. It is a clearly labelled neutral league
            # prior so an empty database produces a usable, low-confidence
            # baseline instead of an UNRESOLVED pipeline.
            home_attack, home_defence, home_n = 1.35, 1.20, 0
            away_attack, away_defence, away_n = 1.10, 1.25, 0
        else:
            home_attack, home_defence, home_n = home_rates
            away_attack, away_defence, away_n = away_rates
        factors: Dict[str, Any] = {
            "home_history_matches": home_n,
            "away_history_matches": away_n,
            "venue_split_used": home_n >= 3 and away_n >= 3,
            "h2h_matches": 0,
            "prior_only": prior_only,
        }

        # H2H is intentionally capped and low-weighted: old meetings must not dominate form.
        h2h = h2h_rows or []
        h2h_values = []
        for row in h2h:
            if row.get("home_goals") is not None and row.get("away_goals") is not None:
                if int(row.get("home_team_id")) == int(home_team_id):
                    h2h_values.append((float(row["home_goals"]), float(row["away_goals"])))
                elif int(row.get("away_team_id")) == int(home_team_id):
                    h2h_values.append((float(row["away_goals"]), float(row["home_goals"])))
        if h2h_values:
            h2h_home = cls._weighted_mean([v[0] for v in h2h_values], prior_mean=home_attack, prior_weight=0)
            h2h_away = cls._weighted_mean([v[1] for v in h2h_values], prior_mean=away_attack, prior_weight=0)
            h2h_weight = min(0.15, 0.05 * len(h2h_values))
            home_attack = (1 - h2h_weight) * home_attack + h2h_weight * h2h_home
            away_attack = (1 - h2h_weight) * away_attack + h2h_weight * h2h_away
            factors["h2h_matches"] = len(h2h_values)
            factors["h2h_weight"] = round(h2h_weight, 3)

        home_context = home_context or {}
        away_context = away_context or {}
        match_context = match_context or {}
        # Multipliers are bounded so untrusted research data cannot create absurd scores.
        home_attack *= cls._bounded(home_context.get("attack_multiplier"), 0.70, 1.30, 1.0)
        away_attack *= cls._bounded(away_context.get("attack_multiplier"), 0.70, 1.30, 1.0)
        home_defence *= cls._bounded(home_context.get("defence_multiplier"), 0.70, 1.30, 1.0)
        away_defence *= cls._bounded(away_context.get("defence_multiplier"), 0.70, 1.30, 1.0)
        # Positive fatigue value means more fatigue and therefore a small performance penalty.
        home_fatigue = cls._bounded(home_context.get("fatigue"), 0.0, 1.0, 0.0)
        away_fatigue = cls._bounded(away_context.get("fatigue"), 0.0, 1.0, 0.0)
        home_motivation = cls._bounded(home_context.get("motivation"), 0.0, 1.0, 0.5)
        away_motivation = cls._bounded(away_context.get("motivation"), 0.0, 1.0, 0.5)
        home_attack *= 1.0 - 0.10 * home_fatigue
        away_attack *= 1.0 - 0.10 * away_fatigue
        home_attack *= 1.0 + 0.06 * (home_motivation - 0.5)
        away_attack *= 1.0 + 0.06 * (away_motivation - 0.5)
        rivalry = cls._bounded(match_context.get("rivalry"), 0.0, 1.0, 0.0)
        weather = cls._bounded(match_context.get("weather_severity"), 0.0, 1.0, 0.0)
        style = cls._bounded(match_context.get("style_goal_factor"), 0.85, 1.15, 1.0)
        context_goal_factor = (1.0 - 0.08 * rivalry - 0.06 * weather) * style
        lam_home = 0.5 * (home_attack + away_defence) * 1.08 * context_goal_factor
        lam_away = 0.5 * (away_attack + home_defence) * context_goal_factor
        lam_home = max(0.05, min(5.0, lam_home))
        lam_away = max(0.05, min(5.0, lam_away))
        factors.update({"rivalry": rivalry, "weather_severity": weather, "context_goal_factor": round(context_goal_factor, 4), "home_fatigue": home_fatigue, "away_fatigue": away_fatigue, "home_motivation": home_motivation, "away_motivation": away_motivation})

        probs_h = [math.exp(-lam_home) * lam_home ** g / math.factorial(g) for g in range(cls.MAX_GOALS + 1)]
        probs_a = [math.exp(-lam_away) * lam_away ** g / math.factorial(g) for g in range(cls.MAX_GOALS + 1)]
        grid = {(h, a): probs_h[h] * probs_a[a] for h in range(cls.MAX_GOALS + 1) for a in range(cls.MAX_GOALS + 1)}
        norm = sum(grid.values())
        grid = {key: value / norm for key, value in grid.items()}
        best = max(grid, key=grid.get)
        return {
            "model_version": cls.MODEL_VERSION,
            "expected_home_goals": round(lam_home, 3), "expected_away_goals": round(lam_away, 3),
            "predicted_home_goals": best[0], "predicted_away_goals": best[1],
            "home_win_probability": round(sum(p for (h, a), p in grid.items() if h > a), 6),
            "draw_probability": round(sum(p for (h, a), p in grid.items() if h == a), 6),
            "away_win_probability": round(sum(p for (h, a), p in grid.items() if h < a), 6),
            "score_probabilities": {f"{h}-{a}": round(p, 8) for (h, a), p in sorted(grid.items(), key=lambda item: item[1], reverse=True)[:10]},
            "sample_size": home_n + away_n,
            "factors": factors,
        }
