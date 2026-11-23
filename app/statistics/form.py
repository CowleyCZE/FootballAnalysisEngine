from __future__ import annotations

import math
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple
from app.statistics.calculators import StatisticsCalculator

DEFAULT_EWMA_ALPHA = 0.28
MIN_VENUE_SPLIT_MATCHES = 3


def _ewma(values: List[float], alpha: float = DEFAULT_EWMA_ALPHA) -> Optional[float]:
    if not values:
        return None
    # Input is oldest to newest so recent matches carry higher weight.
    result = float(values[0])
    for value in values[1:]:
        result = alpha * float(value) + (1.0 - alpha) * result
    return result


def _finite(value: Any) -> Optional[float]:
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    return num if math.isfinite(num) else None


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
            "ga_avg": (ga / valid_count) if valid_count > 0 else None,
        }

    @staticmethod
    def _extract_series(
        rows: List[Mapping[str, Any]],
        team_id: int,
        ratings: Optional[Mapping[int, Tuple[float, float]]] = None,
    ) -> Tuple[List[float], List[float], List[float], List[float]]:
        """Return oldest-to-newest (gd, xgd, points_norm, opp_strength) series."""
        ordered = sorted(
            rows,
            key=lambda r: str(r.get("scheduled_at") or r.get("match_date") or ""),
        )
        gd_series: List[float] = []
        xgd_series: List[float] = []
        pts_series: List[float] = []
        opp_strengths: List[float] = []

        for row in ordered:
            try:
                home_id = int(row["home_team_id"])
                away_id = int(row["away_team_id"])
            except (KeyError, TypeError, ValueError):
                continue
            if team_id not in (home_id, away_id):
                continue
            is_home = home_id == team_id
            h_goals = _finite(row.get("home_goals"))
            a_goals = _finite(row.get("away_goals"))
            if h_goals is None or a_goals is None:
                continue

            gf = h_goals if is_home else a_goals
            ga = a_goals if is_home else h_goals
            _, pts = StatisticsCalculator.calculate_result(int(h_goals), int(a_goals), is_home)

            opp_id = away_id if is_home else home_id
            opp_strength = 1.0
            if ratings and opp_id in ratings:
                opp_atk, opp_def = ratings[opp_id]
                # Stronger opponent has higher attack and lower defence allowance.
                opp_strength = max(0.5, min(1.5, (float(opp_atk) + (2.0 - float(opp_def))) / 2.0))
            opp_strengths.append(opp_strength)

            gd_series.append((gf - ga) * opp_strength)
            pts_series.append((pts / 3.0) * opp_strength)

            hx = _finite(row.get("home_xg"))
            ax = _finite(row.get("away_xg"))
            if hx is not None and ax is not None:
                xg_for = hx if is_home else ax
                xg_against = ax if is_home else hx
                xgd_series.append((xg_for - xg_against) * opp_strength)

        return gd_series, xgd_series, pts_series, opp_strengths

    @classmethod
    def calculate_ewma_form(
        cls,
        matches_data: Iterable[Mapping[str, Any]],
        team_id: int,
        *,
        venue: Optional[str] = None,
        ratings: Optional[Mapping[int, Tuple[float, float]]] = None,
        alpha: float = DEFAULT_EWMA_ALPHA,
        max_matches: int = 10,
    ) -> Dict[str, Any]:
        """Compute opponent-adjusted EWMA form with optional venue split.

        Uses only supplied historical matches and never fabricates missing xG.
        """
        team_id = int(team_id)
        team_rows = [
            r for r in matches_data
            if int(r.get("home_team_id", -1)) == team_id or int(r.get("away_team_id", -1)) == team_id
        ]
        team_rows.sort(key=lambda r: str(r.get("scheduled_at") or r.get("match_date") or ""), reverse=True)
        recent_all = team_rows[:max_matches]

        gd_all, xgd_all, pts_all, opp_all = cls._extract_series(recent_all, team_id, ratings)
        if not gd_all:
            return {
                "sample_size": 0,
                "xg_sample_size": 0,
                "venue_split_used": False,
                "gd_ewma": None,
                "xgd_ewma": None,
                "points_ewma": None,
                "avg_opponent_strength": None,
                "form_score": None,
            }

        gd_val = _ewma(gd_all, alpha)
        xgd_val = _ewma(xgd_all, alpha)
        pts_val = _ewma(pts_all, alpha)

        venue_split_used = False
        if venue in ("home", "away"):
            venue_rows = [
                r for r in team_rows
                if (venue == "home" and int(r.get("home_team_id", -1)) == team_id)
                or (venue == "away" and int(r.get("away_team_id", -1)) == team_id)
            ][:max_matches]
            gd_v, xgd_v, pts_v, _ = cls._extract_series(venue_rows, team_id, ratings)
            if len(gd_v) >= MIN_VENUE_SPLIT_MATCHES:
                venue_split_used = True
                gd_val = 0.65 * _ewma(gd_v, alpha) + 0.35 * gd_val
                pts_val = 0.65 * _ewma(pts_v, alpha) + 0.35 * pts_val
                if len(xgd_v) >= MIN_VENUE_SPLIT_MATCHES and xgd_val is not None:
                    xgd_val = 0.65 * _ewma(xgd_v, alpha) + 0.35 * xgd_val

        # Combine into a bounded, explainable composite form score centered around 0.0.
        components: List[Tuple[float, float]] = []
        if xgd_val is not None:
            components.append((xgd_val, 0.50))
        if gd_val is not None:
            components.append((gd_val, 0.30))
        if pts_val is not None:
            components.append(((pts_val - 0.5) * 2.0, 0.20))
        total_w = sum(w for _, w in components)
        composite = sum(v * w for v, w in components) / total_w if total_w > 0 else 0.0

        return {
            "sample_size": len(gd_all),
            "xg_sample_size": len(xgd_all),
            "venue_split_used": venue_split_used,
            "gd_ewma": round(gd_val, 4) if gd_val is not None else None,
            "xgd_ewma": round(xgd_val, 4) if xgd_val is not None else None,
            "points_ewma": round(pts_val, 4) if pts_val is not None else None,
            "avg_opponent_strength": round(sum(opp_all) / len(opp_all), 4),
            "form_score": round(max(-3.0, min(3.0, composite)), 4),
        }
