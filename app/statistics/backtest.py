"""Walk-forward backtest a kalibrace modelu `poisson-dc-context-v5` (TODO 11.10, bod 2).

Pro každý odehraný zápas v DB se predikce spočítá jen z dat dostupných PŘED výkopem (stejné
vstupy jako ve StatisticalEngine, cutoff = výkop), a porovná se se skutečným výsledkem.
Metriky: úspěšnost 1-X-2, Brier score, log-loss, zásah přesného skóre, MAE gólů a Brier skill
proti klimatologii (konstantní frekvence výsledků).

Ladění je časově rozdělené (první 70 % zápasů = ladění, posledních 30 % = holdout), aby se model
nepřeučil. Konfigurace se zapíše jen s příznakem --write-config a jen když zlepšení potvrdí holdout.

Použití:
    python -m app.statistics.backtest --db database/football.db --competition "Chance Liga"
    python -m app.statistics.backtest --db database/football.db --tune --write-config
"""
from __future__ import annotations

import argparse
import contextlib
import itertools
import json
import math
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, Iterator, List, Mapping, Optional, Sequence

from app.statistics.repository import StatisticsRepository
from app.statistics.score_predictor import ExactScorePredictor

HISTORY_LIMIT = 20
H2H_LIMIT = 8
TRAIN_FRACTION = 0.70
MIN_HOLDOUT = 30  # méně zápasů v holdoutu = výsledek je jen šum, konfigurace se nezapíše
MIN_IMPROVEMENT = 0.001  # minimální zlepšení Brier score na holdoutu

DEFAULT_GRID: Dict[str, Sequence[float]] = {
    "DC_RHO": (-0.12, -0.08, -0.04, 0.0),
    "PRIOR_WEIGHT": (1.0, 1.5, 2.5),
    "FORM_DECAY": (0.08, 0.14, 0.22),
    "XG_WEIGHT": (0.20, 0.35, 0.50),
    "HOME_ADV_SPLIT": (1.00, 1.03, 1.06),
    "HOME_ADV_NO_SPLIT": (1.04, 1.08, 1.12),
}

# TODO 11.19: rozšířené ladnění síly soupeřů. Úplná mřížka by byla příliš velká, proto se prochází po jednom
# parametru (coordinate descent) z nejlepších základních hodnot a změna se přijme jen při zlepšení na tréninku.
# Váhy kontextových multiplikátorů (únava, motivace, rivalita, absence) se neladí: backtest nemá k historickým
# zápasům bezpečně datovaný kontext (jinak by unikala budoucnost) – vyžaduje živé predikce z `match_predictions`.
EXTENDED_GRID: Dict[str, Sequence[float]] = {
    "RATING_SHRINK": (2.0, 5.0, 8.0, 12.0),
    "RATING_MIN": (0.5, 0.6, 0.7),
    "RATING_MAX": (1.4, 1.6, 1.8),
    # Hodnoty za okraji základní mřížky (běh 30. 10. 2026: 5 ze 6 parametrů skončilo na okraji mřížky).
    "DC_RHO": (-0.04, 0.0, 0.03),
    "PRIOR_WEIGHT": (0.5, 0.75, 1.0),
    "FORM_DECAY": (0.04, 0.06, 0.08),
    "HOME_ADV_SPLIT": (1.06, 1.09),
    "HOME_ADV_NO_SPLIT": (1.00, 1.02, 1.04),
}
MIN_REFINE_GAIN = 0.00005  # minimální zlepšení Brier na tréninku pro přijetí změny jednoho parametru
RETUNE_EVERY_MATCHES = 50  # po tolika nových zápasech doporučit nové ladnění


# --- Čisté metriky -----------------------------------------------------------------------------

def outcome_index(home_goals: int, away_goals: int) -> int:
    """0 = výhra domácích, 1 = remíza, 2 = výhra hostů."""
    return 0 if home_goals > away_goals else (1 if home_goals == away_goals else 2)


def score_one(pred: Mapping[str, Any], home_goals: int, away_goals: int) -> Dict[str, float]:
    probs = (
        float(pred["home_win_probability"]),
        float(pred["draw_probability"]),
        float(pred["away_win_probability"]),
    )
    actual = outcome_index(home_goals, away_goals)
    brier = sum((p - (1.0 if i == actual else 0.0)) ** 2 for i, p in enumerate(probs))
    return {
        "outcome": actual,
        "correct": 1.0 if max(range(3), key=lambda i: probs[i]) == actual else 0.0,
        "brier": brier,
        "log_loss": -math.log(max(probs[actual], 1e-12)),
        "exact": 1.0 if (int(pred["predicted_home_goals"]), int(pred["predicted_away_goals"])) == (home_goals, away_goals) else 0.0,
        "goals_abs_error": (abs(float(pred["expected_home_goals"]) - home_goals)
                            + abs(float(pred["expected_away_goals"]) - away_goals)) / 2.0,
    }


def summarize(items: Sequence[Mapping[str, float]]) -> Dict[str, Any]:
    n = len(items)
    if n == 0:
        return {"n": 0}
    freq = [sum(1 for it in items if int(it["outcome"]) == k) / n for k in range(3)]
    baseline_brier = sum(
        sum((freq[i] - (1.0 if i == int(it["outcome"]) else 0.0)) ** 2 for i in range(3)) for it in items
    ) / n
    brier = sum(it["brier"] for it in items) / n
    return {
        "n": n,
        "accuracy_1x2": round(sum(it["correct"] for it in items) / n, 4),
        "baseline_accuracy_home_always": round(freq[0], 4),
        "brier": round(brier, 5),
        "baseline_brier": round(baseline_brier, 5),
        "brier_skill": round(1.0 - brier / baseline_brier, 5) if baseline_brier > 0 else None,
        "log_loss": round(sum(it["log_loss"] for it in items) / n, 5),
        "exact_score_hit": round(sum(it["exact"] for it in items) / n, 4),
        "goals_mae": round(sum(it["goals_abs_error"] for it in items) / n, 4),
        "outcome_frequencies": {"home": round(freq[0], 4), "draw": round(freq[1], 4), "away": round(freq[2], 4)},
    }


# --- Vstupy z DB (bez úniku dat) ----------------------------------------------------------------

def build_inputs(db_path: str, competition: Optional[str] = None, min_history: int = 5) -> List[Dict[str, Any]]:
    """Pro každý odehraný zápas načte vstupy predikce platné před jeho výkopem (cutoff = výkop)."""
    repo = StatisticsRepository(db_path)
    sql = (
        "SELECT m.id AS match_id, m.home_team_id, m.away_team_id, m.scheduled_at, ms.home_goals, ms.away_goals "
        "FROM matches m JOIN match_statistics ms ON ms.match_id = m.id "
        "WHERE ms.home_goals IS NOT NULL AND ms.away_goals IS NOT NULL AND m.scheduled_at IS NOT NULL"
    )
    params: List[Any] = []
    if competition:
        sql += " AND (m.competition = ? OR m.competition_id IN (SELECT id FROM competitions WHERE name = ?))"
        params += [competition, competition]
    sql += " ORDER BY m.scheduled_at ASC, m.id ASC"
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        targets = [dict(r) for r in conn.execute(sql, params).fetchall()]

    inputs: List[Dict[str, Any]] = []
    for t in targets:
        kickoff = t["scheduled_at"]
        hid, aid, mid = int(t["home_team_id"]), int(t["away_team_id"]), int(t["match_id"])
        home_rows = repo.get_team_recent_matches(hid, kickoff, limit=HISTORY_LIMIT, before_kickoff=kickoff)
        away_rows = repo.get_team_recent_matches(aid, kickoff, limit=HISTORY_LIMIT, before_kickoff=kickoff)
        if len(home_rows) < min_history or len(away_rows) < min_history:
            continue
        history = {int(r["match_id"]): r for r in home_rows + away_rows}
        ordered = sorted(history.values(), key=lambda r: str(r.get("scheduled_at") or ""), reverse=True)
        inputs.append({
            "match_id": mid, "home_team_id": hid, "away_team_id": aid, "scheduled_at": kickoff,
            "home_goals": int(t["home_goals"]), "away_goals": int(t["away_goals"]),
            "rows": ordered,
            "h2h_rows": repo.get_head_to_head(hid, aid, kickoff, limit=H2H_LIMIT, before_kickoff=kickoff),
            "league_stats": repo.get_league_goal_stats(mid, kickoff),
            "league_rows": repo.get_league_matches(mid, kickoff),
        })
    return inputs


@contextlib.contextmanager
def _model_params(params: Optional[Mapping[str, float]]) -> Iterator[None]:
    """Dočasně nastaví parametry (výchozí kód + `params`) a po použití obnoví původní stav."""
    P = ExactScorePredictor
    saved = {k: getattr(P, k) for k in P._DEFAULT_PARAMS}
    saved_tuned = dict(P._TUNED)
    P.reset_params()
    if params:
        P.apply_params(params)
    try:
        yield
    finally:
        for key, value in saved.items():
            setattr(P, key, value)
        P._TUNED = saved_tuned


def evaluate(inputs: Sequence[Mapping[str, Any]], params: Optional[Mapping[str, float]] = None) -> Dict[str, Any]:
    """Spočítá metriky modelu s danými parametry (None = výchozí hodnoty z kódu)."""
    items: List[Dict[str, float]] = []
    with _model_params(params):
        for inp in inputs:
            pred = ExactScorePredictor.predict(
                list(inp["rows"]), int(inp["home_team_id"]), int(inp["away_team_id"]),
                h2h_rows=list(inp["h2h_rows"]), league_stats=inp["league_stats"], league_rows=inp["league_rows"],
            )
            if pred:
                items.append(score_one(pred, int(inp["home_goals"]), int(inp["away_goals"])))
    return summarize(items)


# --- Ladění s holdoutem -----------------------------------------------------------------------

def refine_extended(train: Sequence[Mapping[str, Any]], start: Mapping[str, float],
                    extended_grid: Optional[Mapping[str, Sequence[float]]] = None) -> Dict[str, float]:
    """Jeden průchod coordinate descent přes rozšířené parametry; mění se jen při zlepšení tréninkového Brier."""
    grid = dict(extended_grid if extended_grid is not None else EXTENDED_GRID)
    defaults = dict(ExactScorePredictor._DEFAULT_PARAMS)
    current = dict(start)
    for key, values in grid.items():
        current.setdefault(key, defaults[key])
    best_brier = evaluate(train, current).get("brier", float("inf"))
    for key, values in grid.items():
        best_value = current[key]
        for value in values:
            if value == current[key]:
                continue
            candidate = dict(current)
            candidate[key] = value
            # RATING_MIN musí zůstat pod 1,0 a RATING_MAX nad 1,0 (jinak by se mezí ztratil smysl).
            if candidate.get("RATING_MIN", 0.6) >= 1.0 or candidate.get("RATING_MAX", 1.6) <= 1.0:
                continue
            brier = evaluate(train, candidate).get("brier", float("inf"))
            if brier < best_brier - MIN_REFINE_GAIN:
                best_brier, best_value = brier, value
        current[key] = best_value
    return current


def tune(inputs: Sequence[Mapping[str, Any]], grid: Optional[Mapping[str, Sequence[float]]] = None,
         train_fraction: float = TRAIN_FRACTION, extended: bool = False,
         extended_grid: Optional[Mapping[str, Sequence[float]]] = None) -> Dict[str, Any]:
    grid = dict(grid or DEFAULT_GRID)
    ordered = sorted(inputs, key=lambda i: (str(i["scheduled_at"]), int(i["match_id"])))
    split = int(len(ordered) * train_fraction)
    train, holdout = ordered[:split], ordered[split:]
    defaults = dict(ExactScorePredictor._DEFAULT_PARAMS)

    default_train = evaluate(train)
    default_holdout = evaluate(holdout)
    result: Dict[str, Any] = {
        "n_train": len(train), "n_holdout": len(holdout),
        "default_params": defaults, "default_train": default_train, "default_holdout": default_holdout,
        "recommended": False, "best_params": None,
    }
    if len(train) < 20 or not train:
        result["note"] = "Příliš málo zápasů pro ladění (potřeba aspoň 20 v tréninkové části)."
        return result

    keys = list(grid)
    best_params: Optional[Dict[str, float]] = None
    best_key = (float("inf"), float("inf"))
    for combo in itertools.product(*(grid[k] for k in keys)):
        params = dict(zip(keys, combo))
        summary = evaluate(train, params)
        # Při shodě vyhrává kombinace blíž výchozím hodnotám (menší riziko přeučení).
        distance = sum(abs(params[k] - defaults[k]) / max(1e-9, abs(defaults[k])) for k in keys)
        key = (round(summary.get("brier", float("inf")), 6), distance)
        if key < best_key:
            best_params, best_key = params, key
    if extended and best_params is not None:
        best_params = refine_extended(train, best_params, extended_grid)
        result["extended"] = True
    tuned_train = evaluate(train, best_params)
    tuned_holdout = evaluate(holdout, best_params)
    result.update({"best_params": best_params, "tuned_train": tuned_train, "tuned_holdout": tuned_holdout})
    if holdout and tuned_holdout.get("n", 0) >= MIN_HOLDOUT:
        gain = default_holdout["brier"] - tuned_holdout["brier"]
        result["holdout_brier_gain"] = round(gain, 5)
        result["recommended"] = bool(gain >= MIN_IMPROVEMENT and {**defaults, **best_params} != defaults)
        if not result["recommended"]:
            result["note"] = "Ladění nezlepšilo holdout – výchozí parametry zůstávají."
    else:
        result["note"] = f"Holdout má méně než {MIN_HOLDOUT} zápasů – konfigurace se nezapisuje."
    return result


def write_config(path: str, tuning: Mapping[str, Any], competition: Optional[str]) -> bool:
    """Zapíše config/model_params.yaml jen při potvrzeném zlepšení na holdoutu."""
    if not tuning.get("recommended") or not tuning.get("best_params"):
        return False
    import yaml
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "competition": competition,
        "n_train": tuning["n_train"], "n_holdout": tuning["n_holdout"],
        "holdout_brier_default": tuning["default_holdout"]["brier"],
        "holdout_brier_tuned": tuning["tuned_holdout"]["brier"],
        "params": {k: float(v) for k, v in tuning["best_params"].items()},
    }
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        yaml.safe_dump(payload, handle, allow_unicode=True, sort_keys=False)
    return True


def live_feedback_summary(db_path: str) -> Dict[str, Any]:
    """Souhrn ostrých předzápasových predikcí proti skutečným výsledkům (bez seznamu zápasů; read-only)."""
    from app.statistics.prediction_feedback import prediction_feedback
    try:
        data = prediction_feedback(db_path)
    except Exception as exc:  # chybějící tabulka/DB nesmí shodit backtest
        return {"count": 0, "error": type(exc).__name__}
    return {key: data.get(key) for key in ("count", "accuracy_1x2", "brier", "exact_score_hit", "goals_mae")}


def retune_hint(matches_now: int, config_path: str = "config/model_params.yaml",
                every: int = RETUNE_EVERY_MATCHES) -> Dict[str, Any]:
    """Doporučí nové ladnění po `every` nových zápasech od posledního zápisu `model_params.yaml`."""
    tuned_on = None
    try:
        import yaml
        with open(config_path, "r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
        tuned_on = int(data.get("n_train", 0)) + int(data.get("n_holdout", 0))
    except (OSError, ValueError, TypeError, AttributeError):
        tuned_on = None
    if not tuned_on:
        return {"recommended": False, "tuned_on": None, "new_matches": None,
                "note": "Konfigurace ladnění neexistuje – není s čím porovnávat."}
    new = max(0, int(matches_now) - tuned_on)
    return {"recommended": new >= every, "tuned_on": tuned_on, "new_matches": new,
            "note": f"{new} nových zápasů od posledního ladnění (limit {every})."}


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Backtest a kalibrace modelu přesného skóre")
    parser.add_argument("--db", default="database/football.db")
    parser.add_argument("--competition", default=None, help="Název soutěže (výchozí: všechny)")
    parser.add_argument("--min-history", type=int, default=5, help="Min. předchozích zápasů obou týmů")
    parser.add_argument("--tune", action="store_true", help="Prohledat mřížku parametrů (holdout 30 %%)")
    parser.add_argument("--tune-extended", action="store_true",
                        help="Po základní mřížce doladí RATING_SHRINK/RATING_MIN/RATING_MAX (implikuje --tune)")
    parser.add_argument("--write-config", action="store_true", help="Zapsat config/model_params.yaml (jen při zlepšení)")
    parser.add_argument("--report", default="docs/backtest_report.json")
    parser.add_argument("--config-path", default="config/model_params.yaml")
    args = parser.parse_args(argv)

    inputs = build_inputs(args.db, args.competition, args.min_history)
    report: Dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "model_version": ExactScorePredictor.MODEL_VERSION,
        "competition": args.competition,
        "matches_evaluated": len(inputs),
        "default_params": evaluate(inputs),
    }
    print(f"Backtest {ExactScorePredictor.MODEL_VERSION}: {len(inputs)} zápasů")
    report["live_feedback"] = live_feedback_summary(args.db)
    report["retune_hint"] = retune_hint(len(inputs), args.config_path)
    if report["retune_hint"]["recommended"]:
        print(f"  Doporučené nové ladnění: {report['retune_hint']['note']}")
    live = report["live_feedback"]
    if live.get("count"):
        print(f"  Živé predikce: {live['count']} vyhodnocených, 1-X-2 {live['accuracy_1x2']*100:.1f} %, Brier {live['brier']:.4f}")
    base = report["default_params"]
    if base.get("n"):
        print(f"  1-X-2: {base['accuracy_1x2']*100:.1f} % (vždy domácí: {base['baseline_accuracy_home_always']*100:.1f} %) | "
              f"Brier {base['brier']} (klimatologie {base['baseline_brier']}, skill {base['brier_skill']}) | "
              f"přesné skóre {base['exact_score_hit']*100:.1f} % | MAE gólů {base['goals_mae']}")
    if args.tune or args.tune_extended:
        tuning = tune(inputs, extended=args.tune_extended)
        report["tuning"] = tuning
        print(f"  Ladění: train {tuning['n_train']} / holdout {tuning['n_holdout']}, "
              f"doporučeno: {tuning['recommended']} {tuning.get('note', '')}")
        if tuning.get("best_params"):
            print(f"  Nejlepší parametry: {tuning['best_params']}")
        if args.write_config:
            written = write_config(args.config_path, tuning, args.competition)
            report["config_written"] = written
            print(f"  Konfigurace {'zapsána: ' + args.config_path if written else 'nezapsána (bez potvrzeného zlepšení)'}")
            if written:
                # Report i doporučení musí odpovídat právě zapsanému configu (dřív zůstalo „81 nových zápasů“).
                report["retune_hint"] = retune_hint(len(inputs), args.config_path)
                print(f"  Stav ladnění po zápisu: {report['retune_hint']['note']}")
    os.makedirs(os.path.dirname(args.report) or ".", exist_ok=True)
    with open(args.report, "w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
    print(f"  Report: {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
