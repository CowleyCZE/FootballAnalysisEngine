"""Explainable exact-score prediction with form, venue, xG, H2H and context.

The predictor is deterministic and does not fabricate missing team facts. If a
team's history is absent it falls back to a clearly labelled league prior
(derived from the supplied rows when possible). All optional context values are
bounded and reported in ``factors``.

Model: independent Poisson goals with a Dixon-Coles low-score correction.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Mapping, Optional, Tuple


class ExactScorePredictor:
    MODEL_VERSION = "poisson-dc-context-v4"
    MAX_GOALS = 7
    DC_RHO = -0.08  # Dixon-Coles dependence for 0-0 / 1-0 / 0-1 / 1-1
    PRIOR_WEIGHT = 1.5
    DEFAULT_LEAGUE_MEAN = 1.30
    MIN_LEAGUE_MATCHES = 5  # minimální počet zápasů soutěže pro použití ligového průměru

    @staticmethod
    def _weighted_mean(values: List[float], prior_mean: float = 1.25,
                       prior_weight: float = 1.5) -> Optional[float]:
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

    @staticmethod
    def _chronological(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Newest first so recency weights match real time, not list position."""
        return sorted(rows, key=lambda r: str(r.get("scheduled_at") or ""), reverse=True)

    @classmethod
    def _team_rates(cls, rows: List[Dict[str, Any]], team_id: int, venue: str,
                    prior_mean: float = 1.30) -> Optional[Tuple[float, float, int, bool]]:
        rows = cls._chronological(rows)
        all_rows = [r for r in rows if int(r.get("home_team_id")) == team_id or int(r.get("away_team_id")) == team_id]
        venue_rows = [r for r in all_rows if (venue == "home" and int(r.get("home_team_id")) == team_id) or (venue == "away" and int(r.get("away_team_id")) == team_id)]
        if not all_rows:
            return None
        pw = cls.PRIOR_WEIGHT
        all_values = [cls._team_value(r, team_id) for r in all_rows]
        all_attack = cls._weighted_mean([v[0] for v in all_values], prior_mean, pw)
        all_defence = cls._weighted_mean([v[1] for v in all_values], prior_mean, pw)
        # Venue split is useful only with enough observations; otherwise shrink toward all matches.
        split_used = len(venue_rows) >= 3
        if split_used:
            split_values = [cls._team_value(r, team_id) for r in venue_rows]
            split_attack = cls._weighted_mean([v[0] for v in split_values], prior_mean, pw)
            split_defence = cls._weighted_mean([v[1] for v in split_values], prior_mean, pw)
            attack = 0.70 * split_attack + 0.30 * all_attack
            defence = 0.70 * split_defence + 0.30 * all_defence
        else:
            attack, defence = all_attack, all_defence
        return attack, defence, len(all_rows), split_used

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
        league_stats: Optional[Mapping[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        # Ligový průměr gólů: přednost má průměr ze všech zápasů soutěže (≤ cutoff), jinak
        # stávající výpočet z předaných řádků (nebo výchozí hodnota). Zdroj je ve factors.
        league_matches = int((league_stats or {}).get("matches") or 0)
        league_mean_in = (league_stats or {}).get("mean")
        goals_seen = [float(r[k]) for r in rows for k in ("home_goals", "away_goals") if r.get(k) is not None]
        if league_mean_in is not None and league_matches >= cls.MIN_LEAGUE_MATCHES:
            league_mean = float(league_mean_in)
            league_source = "league"
        elif len(goals_seen) >= 10:
            league_mean = sum(goals_seen) / len(goals_seen)
            league_source = "team_rows"
        else:
            league_mean = cls.DEFAULT_LEAGUE_MEAN
            league_source = "default"
        league_mean = max(0.8, min(2.0, league_mean))

        home_rates = cls._team_rates(rows, home_team_id, "home", league_mean)
        away_rates = cls._team_rates(rows, away_team_id, "away", league_mean)
        prior_only = home_rates is None or away_rates is None
        # Missing history is replaced by a neutral league prior for that team
        # only; the other team keeps its real data. This is not a team fact.
        if home_rates is None:
            home_attack, home_defence, home_n, home_split = league_mean * 1.08, league_mean * 0.96, 0, False
        else:
            home_attack, home_defence, home_n, home_split = home_rates
        if away_rates is None:
            away_attack, away_defence, away_n, away_split = league_mean * 0.88, league_mean * 1.00, 0, False
        else:
            away_attack, away_defence, away_n, away_split = away_rates
        factors: Dict[str, Any] = {
            "home_history_matches": home_n,
            "away_history_matches": away_n,
            "venue_split_used": home_split and away_split,
            "league_mean_goals": round(league_mean, 3),
            "league_mean_source": league_source,
            "league_matches": league_matches,
            "h2h_matches": 0,
            "prior_only": prior_only,
        }

        # H2H is intentionally capped and low-weighted: old meetings must not dominate form.
        h2h = cls._chronological(h2h_rows or [])
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
        # Home advantage is already embedded when both venue splits are used.
        home_adv = 1.03 if (home_split and away_split) else 1.08
        lam_home = 0.5 * (home_attack + away_defence) * home_adv * context_goal_factor
        lam_away = 0.5 * (away_attack + home_defence) * context_goal_factor
        lam_home = max(0.05, min(5.0, lam_home))
        lam_away = max(0.05, min(5.0, lam_away))
        factors.update({"home_advantage": home_adv, "rivalry": rivalry, "weather_severity": weather, "context_goal_factor": round(context_goal_factor, 4), "home_fatigue": home_fatigue, "away_fatigue": away_fatigue, "home_motivation": home_motivation, "away_motivation": away_motivation})

        probs_h = [math.exp(-lam_home) * lam_home ** g / math.factorial(g) for g in range(cls.MAX_GOALS + 1)]
        probs_a = [math.exp(-lam_away) * lam_away ** g / math.factorial(g) for g in range(cls.MAX_GOALS + 1)]
        grid = {(h, a): probs_h[h] * probs_a[a] for h in range(cls.MAX_GOALS + 1) for a in range(cls.MAX_GOALS + 1)}
        rho = cls.DC_RHO
        grid[(0, 0)] *= 1.0 - lam_home * lam_away * rho
        grid[(0, 1)] *= 1.0 + lam_home * rho
        grid[(1, 0)] *= 1.0 + lam_away * rho
        grid[(1, 1)] *= 1.0 - rho
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
