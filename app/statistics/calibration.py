"""Cutoff-safe 1X2 probability calibration (Platt / temperature scaling) and diagnostics."""
from __future__ import annotations

import json
import math
import os
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

EPS = 1e-6
DEFAULT_CONFIG_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "config", "calibration_params.json"
)


def _clamp_prob(p: float) -> float:
    return max(EPS, min(1.0 - EPS, float(p)))


def _logit(p: float) -> float:
    p = _clamp_prob(p)
    return math.log(p / (1.0 - p))


def _sigmoid(x: float) -> float:
    x = max(-30.0, min(30.0, float(x)))
    return 1.0 / (1.0 + math.exp(-x))


def _normalize_triple(probs: Tuple[float, float, float]) -> Tuple[float, float, float]:
    total = sum(probs)
    if total <= 0 or not math.isfinite(total):
        return (1.0 / 3.0, 1.0 / 3.0, 1.0 / 3.0)
    return (probs[0] / total, probs[1] / total, probs[2] / total)


def brier_score_1x2(
    predictions: Sequence[Tuple[float, float, float]],
    outcomes: Sequence[int],
) -> Optional[float]:
    """Multiclass Brier score for 1X2 outcomes (0=home, 1=draw, 2=away)."""
    if not predictions or len(predictions) != len(outcomes):
        return None
    total = 0.0
    for probs, outcome in zip(predictions, outcomes):
        for idx in range(3):
            target = 1.0 if idx == outcome else 0.0
            total += (float(probs[idx]) - target) ** 2
    return total / len(predictions)


def calibration_curve(
    predictions: Sequence[Tuple[float, float, float]],
    outcomes: Sequence[int],
    *,
    bins: int = 10,
) -> Dict[str, Any]:
    """Compute reliability bins and Expected Calibration Error (ECE) across 1X2."""
    if not predictions or len(predictions) != len(outcomes) or bins < 1:
        return {"ece": None, "bins": []}
    bucket_preds: List[List[float]] = [[] for _ in range(bins)]
    bucket_hits: List[List[float]] = [[] for _ in range(bins)]
    for probs, outcome in zip(predictions, outcomes):
        for idx in range(3):
            p = _clamp_prob(probs[idx])
            hit = 1.0 if idx == outcome else 0.0
            b = min(bins - 1, int(p * bins))
            bucket_preds[b].append(p)
            bucket_hits[b].append(hit)
    total_obs = 3 * len(predictions)
    ece = 0.0
    bin_rows = []
    for idx in range(bins):
        count = len(bucket_preds[idx])
        if count == 0:
            continue
        mean_pred = sum(bucket_preds[idx]) / count
        mean_obs = sum(bucket_hits[idx]) / count
        ece += (count / total_obs) * abs(mean_pred - mean_obs)
        bin_rows.append({
            "bin": idx,
            "count": count,
            "mean_predicted": round(mean_pred, 4),
            "mean_observed": round(mean_obs, 4),
        })
    return {"ece": round(ece, 6), "bins": bin_rows}


class PlattCalibrator:
    """Per-class Platt scaling for 1X2 probabilities with simplex renormalization."""

    def __init__(self, params: Optional[Mapping[str, Tuple[float, float]]] = None) -> None:
        default = {"home": (1.0, 0.0), "draw": (1.0, 0.0), "away": (1.0, 0.0)}
        if params:
            for key in ("home", "draw", "away"):
                if key in params and len(params[key]) == 2:
                    a, b = float(params[key][0]), float(params[key][1])
                    if math.isfinite(a) and math.isfinite(b):
                        default[key] = (a, b)
        self.params: Dict[str, Tuple[float, float]] = default

    @classmethod
    def fit(
        cls,
        predictions: Sequence[Tuple[float, float, float]],
        outcomes: Sequence[int],
        *,
        lr: float = 0.05,
        steps: int = 250,
        l2: float = 0.01,
    ) -> "PlattCalibrator":
        """Fit Platt scaling parameters strictly on supplied historical observations."""
        if len(predictions) < 10 or len(predictions) != len(outcomes):
            return cls()
        keys = ("home", "draw", "away")
        fitted: Dict[str, Tuple[float, float]] = {}
        n = float(len(predictions))
        for idx, key in enumerate(keys):
            logits = [_logit(p[idx]) for p in predictions]
            targets = [1.0 if o == idx else 0.0 for o in outcomes]
            a, b = 1.0, 0.0
            for _ in range(steps):
                grad_a = 0.0
                grad_b = 0.0
                for z, y in zip(logits, targets):
                    pred = _sigmoid(a * z + b)
                    diff = pred - y
                    grad_a += diff * z
                    grad_b += diff
                grad_a = grad_a / n + l2 * (a - 1.0)
                grad_b = grad_b / n + l2 * b
                a -= lr * grad_a
                b -= lr * grad_b
                a = max(0.25, min(4.0, a))
                b = max(-2.0, min(2.0, b))
            fitted[key] = (round(a, 6), round(b, 6))
        return cls(fitted)

    def calibrate(self, p_home: float, p_draw: float, p_away: float) -> Tuple[float, float, float]:
        """Apply calibration to raw 1X2 probabilities and renormalize to sum to 1."""
        raw = (p_home, p_draw, p_away)
        keys = ("home", "draw", "away")
        calibrated = []
        for prob, key in zip(raw, keys):
            a, b = self.params[key]
            calibrated.append(_sigmoid(a * _logit(prob) + b))
        return _normalize_triple((calibrated[0], calibrated[1], calibrated[2]))

    def to_dict(self) -> Dict[str, List[float]]:
        return {k: [v[0], v[1]] for k, v in self.params.items()}

    def save(self, path: Optional[str] = None) -> str:
        target = path or DEFAULT_CONFIG_PATH
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "w", encoding="utf-8") as handle:
            json.dump({"method": "platt", "params": self.to_dict()}, handle, indent=2)
        return target

    @classmethod
    def load(cls, path: Optional[str] = None) -> Optional["PlattCalibrator"]:
        target = path or DEFAULT_CONFIG_PATH
        if not os.path.exists(target):
            return None
        try:
            with open(target, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            params = data.get("params") if isinstance(data, dict) else None
            if not isinstance(params, dict):
                return None
            return cls({k: (float(v[0]), float(v[1])) for k, v in params.items() if isinstance(v, list) and len(v) == 2})
        except Exception:
            return None
