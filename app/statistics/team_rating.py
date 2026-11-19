"""Cutoff-safe xG-based team attack and defence ratings.

The ratings describe a team's expected xG production and xGA allowance relative
to the league mean. They use only completed matches supplied by the caller and
never infer missing xG values.
"""
from __future__ import annotations

import math
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

DEFAULT_ITERATIONS = 3
DEFAULT_SHRINK = 5.0
DEFAULT_MIN_RATING = 0.6
DEFAULT_MAX_RATING = 1.6


def _finite_non_negative(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number >= 0 else None


def filter_matches_before(rows: Iterable[Mapping[str, Any]], cutoff: str) -> List[Mapping[str, Any]]:
    """Return completed matches strictly before an ISO date/datetime cutoff."""
    result = []
    for row in rows:
        played_at = str(row.get("scheduled_at") or row.get("match_date") or "")
        if not played_at or played_at >= cutoff:
            continue
        if row.get("home_goals") is None or row.get("away_goals") is None:
            continue
        result.append(row)
    return result


def compute_xg_team_ratings(
    rows: Iterable[Mapping[str, Any]],
    league_mean: float,
    *,
    iterations: int = DEFAULT_ITERATIONS,
    shrink: float = DEFAULT_SHRINK,
    rating_min: float = DEFAULT_MIN_RATING,
    rating_max: float = DEFAULT_MAX_RATING,
) -> Dict[int, Tuple[float, float]]:
    """Compute opponent-adjusted xG attack and defence ratings.

    Returns ``{team_id: (attack_rating, defence_rating)}``. A rating of 1.0 is
    league average; attack above 1.0 creates more xG than average, while defence
    above 1.0 allows more xG than average.
    """
    if league_mean <= 0 or not math.isfinite(league_mean):
        return {}
    observations: Dict[int, List[Tuple[int, float, float]]] = {}
    for row in rows:
        try:
            home = int(row["home_team_id"])
            away = int(row["away_team_id"])
        except (KeyError, TypeError, ValueError):
            continue
        home_xg = _finite_non_negative(row.get("home_xg"))
        away_xg = _finite_non_negative(row.get("away_xg"))
        home_xga = _finite_non_negative(row.get("home_xga"))
        away_xga = _finite_non_negative(row.get("away_xga"))
        if None in (home_xg, away_xg, home_xga, away_xga):
            continue
        observations.setdefault(home, []).append((away, float(home_xg), float(home_xga)))
        observations.setdefault(away, []).append((home, float(away_xg), float(away_xga)))
    if not observations:
        return {}
    lo = max(0.05, float(rating_min))
    hi = max(lo, float(rating_max))
    shrink = max(0.0, float(shrink))
    attack = {team: 1.0 for team in observations}
    defence = {team: 1.0 for team in observations}
    for _ in range(max(0, int(iterations))):
        next_attack: Dict[int, float] = {}
        next_defence: Dict[int, float] = {}
        for team, games in observations.items():
            sample = len(games)
            raw_attack = sum(xg_for / max(0.05, defence[opponent]) for opponent, xg_for, _ in games) / sample / league_mean
            raw_defence = sum(xga_for / max(0.05, attack[opponent]) for opponent, _, xga_for in games) / sample / league_mean
            next_attack[team] = min(hi, max(lo, (sample * raw_attack + shrink) / (sample + shrink)))
            next_defence[team] = min(hi, max(lo, (sample * raw_defence + shrink) / (sample + shrink)))
        attack, defence = next_attack, next_defence
    return {team: (round(attack[team], 6), round(defence[team], 6)) for team in observations}
