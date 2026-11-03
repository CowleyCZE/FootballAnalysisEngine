"""Cutoff-safe derived attacking features calculated from completed match xG."""
from __future__ import annotations

import math
from typing import Any, Dict, Iterable, Mapping, Optional

PENALTY_XG_ESTIMATE = 0.79

# TODO 11.34: metriky, které vyžadují data, jež feed ligy nemusí poskytovat (střelecké souřadnice,
# penalty, game-state). Bez jediného pozorování se nezobrazují jako „N/A“, ale jako nepodporované feedem.
FEED_DEPENDENT_METRICS = frozenset({
    "npxg_for_ewma", "npxg_against_ewma", "npxgd_ewma",
    "game_state_adj_xg_for_ewma", "game_state_adj_xg_against_ewma",
})
UNSUPPORTED_BY_FEED_LABEL = "nepodporováno feedem ligy"


def metric_availability(metric: str, value: Optional[float], sample_size: Optional[int]) -> Optional[str]:
    """Vrátí "UNSUPPORTED_BY_FEED", pokud metrika závislá na datech feedu nemá hodnotu ani jediný vzorek."""
    if metric in FEED_DEPENDENT_METRICS and value is None and not sample_size:
        return "UNSUPPORTED_BY_FEED"
    return None


def derive_npxg(total_xg: Optional[float], penalty_attempts: Optional[int],
                penalty_xg: Optional[float] = None) -> Optional[float]:
    """Estimate npxG only when penalty information is supplied; never infer attempts."""
    if total_xg is None or (penalty_attempts is None and penalty_xg is None):
        return None
    removed = float(penalty_xg) if penalty_xg is not None else int(penalty_attempts) * PENALTY_XG_ESTIMATE
    return round(max(0.0, float(total_xg) - removed), 3)


def _value(row: Mapping[str, Any], key: str) -> Optional[float]:
    try:
        value = float(row[key])
        return value if math.isfinite(value) and 0 <= value <= 8 else None
    except (KeyError, TypeError, ValueError):
        return None


def _ewma(values: list[float], alpha: float = 0.25) -> Optional[float]:
    if not values:
        return None
    result = values[0]  # input is oldest to newest
    for value in values[1:]:
        result = alpha * value + (1.0 - alpha) * result
    return result


def _sigmoid(value: float) -> float:
    value = max(-30.0, min(30.0, value))
    return 1.0 / (1.0 + math.exp(-value))


def calculate_team_features(team_id: int, matches: Iterable[Mapping[str, Any]],
                            xg_events: Iterable[Mapping[str, Any]] = (),
                            ewma_alpha: float = 0.25, elo_k: float = 24.0) -> Dict[str, Any]:
    """Return npxG form, xG-Elo and state-adjusted rates using only supplied past rows.

    Matches must be newest first; xG Elo events must contain only completed observations
    before the requested cutoff and can be in any order. Missing npxG/state-adjusted data
    remain None; total xG is never mislabeled as npxG or game-state adjusted xG.
    """
    team_id = int(team_id)

    def unique_rows(rows: Iterable[Mapping[str, Any]], date_key: str) -> list[Mapping[str, Any]]:
        by_key: Dict[tuple, Mapping[str, Any]] = {}
        for row in rows:
            home, away = int(row.get("home_team_id", -1)), int(row.get("away_team_id", -1))
            date = str(row.get(date_key) or row.get("scheduled_at") or row.get("match_date") or "")[:10]
            if home < 0 or away < 0 or not date:
                continue
            key = (date, home, away)
            prior = by_key.get(key)
            score = sum(row.get(k) is not None for k in
                        ("home_npxg", "away_npxg", "home_gs_adj_xg", "away_gs_adj_xg", "home_xg", "away_xg"))
            prior_score = sum(prior.get(k) is not None for k in
                              ("home_npxg", "away_npxg", "home_gs_adj_xg", "away_gs_adj_xg", "home_xg", "away_xg")) if prior else -1
            if prior is None or score > prior_score:
                by_key[key] = row
        return list(by_key.values())

    team_rows = [r for r in unique_rows(matches, "scheduled_at")
                 if team_id in (int(r.get("home_team_id", -1)), int(r.get("away_team_id", -1)))]
    team_rows.sort(key=lambda r: str(r.get("scheduled_at") or r.get("match_date") or ""), reverse=True)
    team_rows = team_rows[:10]
    npxg_for, npxg_against, xgd = [], [], []
    gs_for, gs_against = [], []
    npxg_count = 0
    for row in reversed(team_rows):  # oldest to newest
        is_home = int(row.get("home_team_id", -1)) == team_id
        n_for = _value(row, "home_npxg" if is_home else "away_npxg")
        n_against = _value(row, "away_npxg" if is_home else "home_npxg")
        x_for = _value(row, "home_xg" if is_home else "away_xg")
        x_against = _value(row, "away_xg" if is_home else "home_xg")
        if n_for is not None and n_against is not None:
            npxg_for.append(n_for)
            npxg_against.append(n_against)
            npxg_count += 1
        if x_for is not None and x_against is not None:
            xgd.append(x_for - x_against)
        a_for = _value(row, "home_gs_adj_xg" if is_home else "away_gs_adj_xg")
        a_against = _value(row, "away_gs_adj_xg" if is_home else "home_gs_adj_xg")
        if a_for is not None and a_against is not None:
            gs_for.append(a_for)
            gs_against.append(a_against)

    # xG performance Elo: compare the pre-match rating expectation with a bounded
    # performance score derived from xGD. It starts at a neutral league rating.
    ratings: Dict[int, float] = {}
    rating_counts: Dict[int, int] = {}
    event_rows = sorted(unique_rows(xg_events, "match_date"),
                        key=lambda r: str(r.get("scheduled_at") or r.get("match_date") or ""))
    elo_count = 0
    for row in event_rows:
        h, a = int(row.get("home_team_id", -1)), int(row.get("away_team_id", -1))
        hx = _value(row, "home_npxg")
        ax = _value(row, "away_npxg")
        if hx is None:
            hx = _value(row, "home_xg")
        if ax is None:
            ax = _value(row, "away_xg")
        if h < 0 or a < 0 or hx is None or ax is None:
            continue
        rh, ra = ratings.get(h, 1500.0), ratings.get(a, 1500.0)
        expected_home = 1.0 / (1.0 + 10.0 ** (-((rh + 35.0) - ra) / 400.0))
        # smooth xG-difference performance score; unlike result Elo this does not
        # discard chance quality when a low-probability result occurs.
        actual_home = _sigmoid((hx - ax) / 0.75)
        delta = elo_k * (actual_home - expected_home)
        ratings[h], ratings[a] = rh + delta, ra - delta
        rating_counts[h] = rating_counts.get(h, 0) + 1
        rating_counts[a] = rating_counts.get(a, 0) + 1
        elo_count += 1

    return {
        "npxg_for_ewma": _ewma(npxg_for, ewma_alpha),
        "npxg_against_ewma": _ewma(npxg_against, ewma_alpha),
        "npxgd_ewma": (_ewma([a - b for a, b in zip(npxg_for, npxg_against)], ewma_alpha)
                       if npxg_for else None),
        "npxg_sample_size": npxg_count,
        "xgd_ewma": _ewma(xgd, ewma_alpha),
        "xg_sample_size": len(xgd),
        "game_state_adj_xg_for_ewma": _ewma(gs_for, ewma_alpha),
        "game_state_adj_xg_against_ewma": _ewma(gs_against, ewma_alpha),
        "game_state_adj_sample_size": len(gs_for),
        "xg_elo": round(ratings.get(team_id, 1500.0), 2),
        "xg_elo_sample_size": rating_counts.get(team_id, 0),
    }
