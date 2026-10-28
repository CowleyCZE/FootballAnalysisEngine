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
    MODEL_VERSION = "poisson-dc-context-v7"
    MAX_GOALS = 7
    DC_RHO = -0.08  # Dixon-Coles dependence for 0-0 / 1-0 / 0-1 / 1-1
    PRIOR_WEIGHT = 1.5
    DEFAULT_LEAGUE_MEAN = 1.30
    XG_WEIGHT = 0.35  # podíl xG ve spojení s góly, pokud jsou dostupné oba údaje
    MIN_LEAGUE_MATCHES = 5  # minimální počet zápasů soutěže pro použití ligového průměru
    RATING_ITERATIONS = 3  # kroky iterativní normalizace síly soupeřů
    RATING_SHRINK = 5.0  # pseudo-zápasy shrinkage k 1,0
    RATING_BOUNDS = (0.6, 1.6)
    FORM_DECAY = 0.14  # exponenciální úbytek váhy starších zápasů (váha = exp(-FORM_DECAY * pořadí))
    HOME_ADV_SPLIT = 1.03  # domácí výhoda, když už je zahrnutá v domácích/venkovních rozděleních
    HOME_ADV_NO_SPLIT = 1.08  # domácí výhoda bez rozdělení domácí/venku

    # Laditelné parametry (backtest, TODO 11.10 bod 2): rozsahy chrání model před absurdními hodnotami.
    TUNABLE_BOUNDS = {
        "DC_RHO": (-0.25, 0.05),
        "PRIOR_WEIGHT": (0.5, 4.0),
        "FORM_DECAY": (0.02, 0.40),
        "XG_WEIGHT": (0.0, 0.70),
        "HOME_ADV_SPLIT": (0.95, 1.15),
        "HOME_ADV_NO_SPLIT": (1.00, 1.20),
    }
    _DEFAULT_PARAMS = {
        "DC_RHO": -0.08, "PRIOR_WEIGHT": 1.5, "FORM_DECAY": 0.14, "XG_WEIGHT": 0.35,
        "HOME_ADV_SPLIT": 1.03, "HOME_ADV_NO_SPLIT": 1.08,
    }
    _TUNED: Dict[str, float] = {}

    @classmethod
    def apply_params(cls, params: Mapping[str, Any]) -> Dict[str, float]:
        """Nastaví laditelné parametry (jen známé klíče, hodnoty mimo rozsah se ignorují). Vrací použité."""
        applied: Dict[str, float] = {}
        for key, value in (params or {}).items():
            bounds = cls.TUNABLE_BOUNDS.get(key)
            try:
                number = float(value)
            except (TypeError, ValueError):
                continue
            if bounds is None or not math.isfinite(number) or not (bounds[0] <= number <= bounds[1]):
                continue
            setattr(cls, key, number)
            applied[key] = number
        cls._TUNED = {k: getattr(cls, k) for k in cls._DEFAULT_PARAMS if getattr(cls, k) != cls._DEFAULT_PARAMS[k]}
        return applied

    @classmethod
    def reset_params(cls) -> None:
        for key, value in cls._DEFAULT_PARAMS.items():
            setattr(cls, key, value)
        cls._TUNED = {}

    @classmethod
    def opponent_ratings(cls, league_rows: Optional[List[Mapping[str, Any]]],
                         league_mean: float) -> Dict[int, Tuple[float, float]]:
        """Relativní útok/obrana týmů vzhledem k lize (1,0 = průměr; obrana >1 = dostává víc gólů).

        Iterativní normalizace na kvalitu soupeřů, shrinkage k 1,0. Prázdný výsledek bez dat.
        """
        games: Dict[int, List[Tuple[int, float, float]]] = {}
        for r in league_rows or []:
            if r.get("home_goals") is None or r.get("away_goals") is None:
                continue
            h, a = int(r["home_team_id"]), int(r["away_team_id"])
            hg, ag = float(r["home_goals"]), float(r["away_goals"])
            games.setdefault(h, []).append((a, hg, ag))
            games.setdefault(a, []).append((h, ag, hg))
        if not games or league_mean <= 0:
            return {}
        lo, hi = cls.RATING_BOUNDS
        atk = {t: 1.0 for t in games}
        dfn = {t: 1.0 for t in games}
        for _ in range(cls.RATING_ITERATIONS):
            new_atk, new_dfn = {}, {}
            for t, gl in games.items():
                n = len(gl)
                scored = sum(gf / dfn[o] for o, gf, _ in gl) / n / league_mean
                conceded = sum(ga / atk[o] for o, _, ga in gl) / n / league_mean
                new_atk[t] = max(lo, min(hi, (n * scored + cls.RATING_SHRINK) / (n + cls.RATING_SHRINK)))
                new_dfn[t] = max(lo, min(hi, (n * conceded + cls.RATING_SHRINK) / (n + cls.RATING_SHRINK)))
            atk, dfn = new_atk, new_dfn
        return {t: (atk[t], dfn[t]) for t in games}

    @staticmethod
    def _weighted_mean(values: List[float], prior_mean: float = 1.25,
                       prior_weight: float = 1.5) -> Optional[float]:
        values = [float(v) for v in values if v is not None and math.isfinite(float(v))]
        if not values:
            return None
        weights = [math.exp(-ExactScorePredictor.FORM_DECAY * i) for i in range(len(values))]
        return (sum(v * w for v, w in zip(values, weights)) + prior_mean * prior_weight) / (sum(weights) + prior_weight)

    @classmethod
    def _team_value(cls, row: Mapping[str, Any], team_id: int,
                    ratings: Optional[Mapping[int, Tuple[float, float]]] = None) -> Tuple[float, float]:
        is_home = int(row["home_team_id"]) == int(team_id)
        goals = row.get("home_goals" if is_home else "away_goals")
        against = row.get("away_goals" if is_home else "home_goals")
        xg = row.get("home_xg" if is_home else "away_xg")
        xga = row.get("home_xga" if is_home else "away_xga")
        # Blend observed goals with xG, but use the available series when one is absent.
        xg_weight = cls.XG_WEIGHT
        goal_weight = 1.0 - xg_weight
        attack = goal_weight * float(goals) + xg_weight * float(xg) if goals is not None and xg is not None else (float(xg) if xg is not None else float(goals))
        defence = goal_weight * float(against) + xg_weight * float(xga) if against is not None and xga is not None else (float(xga) if xga is not None else float(against))
        if ratings:
            opp = int(row["away_team_id"] if is_home else row["home_team_id"])
            opp_atk, opp_def = ratings.get(opp, (1.0, 1.0))
            # Góly proti silné obraně mají větší váhu a naopak.
            attack /= max(0.1, opp_def)
            defence /= max(0.1, opp_atk)
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
                    prior_mean: float = 1.30,
                    ratings: Optional[Mapping[int, Tuple[float, float]]] = None) -> Optional[Tuple[float, float, int, bool]]:
        rows = cls._chronological(rows)
        all_rows = [r for r in rows if int(r.get("home_team_id")) == team_id or int(r.get("away_team_id")) == team_id]
        venue_rows = [r for r in all_rows if (venue == "home" and int(r.get("home_team_id")) == team_id) or (venue == "away" and int(r.get("away_team_id")) == team_id)]
        if not all_rows:
            return None
        pw = cls.PRIOR_WEIGHT
        all_values = [cls._team_value(r, team_id, ratings) for r in all_rows]
        all_attack = cls._weighted_mean([v[0] for v in all_values], prior_mean, pw)
        all_defence = cls._weighted_mean([v[1] for v in all_values], prior_mean, pw)
        # Venue split is useful only with enough observations; otherwise shrink toward all matches.
        split_used = len(venue_rows) >= 3
        if split_used:
            split_values = [cls._team_value(r, team_id, ratings) for r in venue_rows]
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
        league_rows: Optional[List[Mapping[str, Any]]] = None,
        home_xg_rates: Optional[Mapping[str, Any]] = None,
        away_xg_rates: Optional[Mapping[str, Any]] = None,
        team_features: Optional[Mapping[str, Mapping[str, Any]]] = None,
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

        ratings: Dict[int, Tuple[float, float]] = {}
        if league_rows and len(league_rows) >= cls.MIN_LEAGUE_MATCHES:
            ratings = cls.opponent_ratings(league_rows, league_mean)
        home_rates = cls._team_rates(rows, home_team_id, "home", league_mean, ratings or None)
        away_rates = cls._team_rates(rows, away_team_id, "away", league_mean, ratings or None)
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
        xg_used: Dict[str, Any] = {}
        home_values = [home_attack, home_defence]
        away_values = [away_attack, away_defence]
        history_xg_counts = {
            "home": sum(1 for r in rows
                        if int(r.get("home_team_id", -1)) == int(home_team_id)
                        or int(r.get("away_team_id", -1)) == int(home_team_id)
                        if (r.get("home_xg") if int(r.get("home_team_id", -1)) == int(home_team_id) else r.get("away_xg")) is not None),
            "away": sum(1 for r in rows
                        if int(r.get("home_team_id", -1)) == int(away_team_id)
                        or int(r.get("away_team_id", -1)) == int(away_team_id)
                        if (r.get("home_xg") if int(r.get("home_team_id", -1)) == int(away_team_id) else r.get("away_xg")) is not None),
        }
        for side, supplied, values in (
            ("home", home_xg_rates, home_values),
            ("away", away_xg_rates, away_values),
        ):
            # Completed match rows already contain xG; don't count the same sample twice.
            if not supplied or history_xg_counts[side] >= 3:
                continue
            try:
                attack_xg = float(supplied["attack"])
                defence_xg = float(supplied["defence"])
                n_xg = max(0, int(supplied.get("sample_size") or 0))
                if not all(math.isfinite(v) and 0 <= v <= 8 for v in (attack_xg, defence_xg)):
                    continue
            except (KeyError, TypeError, ValueError):
                continue
            # Shrink xG-only/current-season evidence toward the established rates.
            weight = min(0.60, n_xg / (n_xg + 5.0)) if n_xg else 0.25
            values[0] = (1 - weight) * values[0] + weight * attack_xg
            values[1] = (1 - weight) * values[1] + weight * defence_xg
            xg_used[side] = {"source": supplied.get("source", "unknown"),
                             "sample_size": n_xg, "weight": round(weight, 3),
                             "venue_split_used": bool(supplied.get("venue_split_used"))}
        home_attack, home_defence = home_values
        away_attack, away_defence = away_values
        feature_adjustments: Dict[str, Any] = {}
        for side, values, feature in (
            ("home", home_values, (team_features or {}).get("home", {})),
            ("away", away_values, (team_features or {}).get("away", {})),
        ):
            if int(feature.get("npxg_sample_size") or 0) >= 3:
                attack = feature.get("npxg_for_ewma")
                defence = feature.get("npxg_against_ewma")
                if attack is not None and defence is not None:
                    values[0] = 0.75 * values[0] + 0.25 * float(attack)
                    values[1] = 0.75 * values[1] + 0.25 * float(defence)
                    feature_adjustments.setdefault(side, {})["npxg_ewma_weight"] = 0.25
            if int(feature.get("game_state_adj_sample_size") or 0) >= 3:
                attack = feature.get("game_state_adj_xg_for_ewma")
                defence = feature.get("game_state_adj_xg_against_ewma")
                if attack is not None and defence is not None:
                    values[0] = 0.80 * values[0] + 0.20 * float(attack)
                    values[1] = 0.80 * values[1] + 0.20 * float(defence)
                    feature_adjustments.setdefault(side, {})["game_state_adjusted_xg_weight"] = 0.20
            elo = feature.get("xg_elo")
            if elo is not None and int(feature.get("xg_elo_sample_size") or 0) >= 3:
                multiplier = max(0.90, min(1.10, 10.0 ** ((float(elo) - 1500.0) / 1200.0)))
                values[0] *= multiplier
                values[1] /= multiplier
                feature_adjustments.setdefault(side, {})["xg_elo_multiplier"] = round(multiplier, 4)
        home_attack, home_defence = home_values
        away_attack, away_defence = away_values
        factors: Dict[str, Any] = {
            "home_history_matches": home_n,
            "away_history_matches": away_n,
            "venue_split_used": home_split and away_split,
            "league_mean_goals": round(league_mean, 3),
            "league_mean_source": league_source,
            "league_matches": league_matches,
            "opponent_adjusted": bool(ratings),
            "h2h_matches": 0,
            "prior_only": prior_only,
            "historical_xg_matches": history_xg_counts,
        }
        if xg_used:
            factors["imported_xg"] = xg_used
        if team_features:
            factors["team_features"] = {
                side: {key: (round(float(value), 4) if isinstance(value, (int, float)) and value is not None else value)
                       for key, value in feature.items()}
                for side, feature in team_features.items()
            }
            if feature_adjustments:
                factors["team_feature_adjustments"] = feature_adjustments
        if cls._TUNED:
            factors["tuned_params"] = dict(cls._TUNED)

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
        home_att_mult = cls._bounded(home_context.get("attack_multiplier"), 0.70, 1.30, 1.0)
        away_att_mult = cls._bounded(away_context.get("attack_multiplier"), 0.70, 1.30, 1.0)
        home_def_mult = cls._bounded(home_context.get("defence_multiplier"), 0.70, 1.30, 1.0)
        away_def_mult = cls._bounded(away_context.get("defence_multiplier"), 0.70, 1.30, 1.0)
        home_attack *= home_att_mult
        away_attack *= away_att_mult
        home_defence *= home_def_mult
        away_defence *= away_def_mult
        if (home_att_mult, home_def_mult, away_att_mult, away_def_mult) != (1.0, 1.0, 1.0, 1.0):
            factors["context_multipliers"] = {
                "home_attack": round(home_att_mult, 4), "home_defence": round(home_def_mult, 4),
                "away_attack": round(away_att_mult, 4), "away_defence": round(away_def_mult, 4),
                "home_absences": int(home_context.get("absences_counted") or 0),
                "away_absences": int(away_context.get("absences_counted") or 0),
            }
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
        style = cls._bounded(match_context.get("style_goal_factor"), 0.85, 1.15, 1.0)
        context_goal_factor = (1.0 - 0.08 * rivalry) * style
        # Home advantage is already embedded when both venue splits are used.
        home_adv = cls.HOME_ADV_SPLIT if (home_split and away_split) else cls.HOME_ADV_NO_SPLIT
        lam_home = 0.5 * (home_attack + away_defence) * home_adv * context_goal_factor
        lam_away = 0.5 * (away_attack + home_defence) * context_goal_factor
        lam_home = max(0.05, min(5.0, lam_home))
        lam_away = max(0.05, min(5.0, lam_away))
        factors.update({"home_advantage": home_adv, "rivalry": rivalry, "context_goal_factor": round(context_goal_factor, 4), "home_fatigue": home_fatigue, "away_fatigue": away_fatigue, "home_motivation": home_motivation, "away_motivation": away_motivation})

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
            # Přípona "+tuned" = použity parametry z backtestu (config/model_params.yaml) → predikce je dohledatelná.
            "model_version": cls.MODEL_VERSION + ("+tuned" if cls._TUNED else ""),
            "expected_home_goals": round(lam_home, 3), "expected_away_goals": round(lam_away, 3),
            "predicted_home_goals": best[0], "predicted_away_goals": best[1],
            "home_win_probability": round(sum(p for (h, a), p in grid.items() if h > a), 6),
            "draw_probability": round(sum(p for (h, a), p in grid.items() if h == a), 6),
            "away_win_probability": round(sum(p for (h, a), p in grid.items() if h < a), 6),
            "score_probabilities": {f"{h}-{a}": round(p, 8) for (h, a), p in sorted(grid.items(), key=lambda item: item[1], reverse=True)[:10]},
            "sample_size": home_n + away_n,
            "factors": factors,
        }


def load_tuned_params(path: Optional[str] = None) -> Dict[str, float]:
    """Načte parametry z config/model_params.yaml (vytváří je jen `app.statistics.backtest --write-config`).
    Soubor není – žádná změna; neplatné/mimo rozsah hodnoty se ignorují."""
    import os
    if os.getenv("FAE_TUNED_PARAMS", "1") == "0":
        return {}
    config_path = path or os.path.join(os.path.dirname(__file__), "..", "..", "config", "model_params.yaml")
    if not os.path.exists(config_path):
        return {}
    try:
        import yaml
        with open(config_path, "r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
        params = data.get("params", data) if isinstance(data, dict) else {}
        return ExactScorePredictor.apply_params(params)
    except Exception:
        return {}


load_tuned_params()
