"""Map cited research snapshots to bounded predictor context values.

The mapper is deliberately conservative: it only emits a correction when a
stored, validated claim contains explicit contextual terms. Missing or vague
research remains missing rather than being guessed.
"""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from urllib.parse import urlparse


class ResearchContextMapper:
    FATIGUE_TERMS = ("fatigue", "fixture congestion", "short rest", "rest days", "travel", "rotation", "únava", "odpočinek", "cestov")
    MOTIVATION_TERMS = ("must win", "qualification", "relegation", "title race", "objective", "motiv", "playoff", "postup", "sestup")

    # Absence/lineup correction: only verified claims (>= 2 independent publishers, source date <= cutoff).
    ABSENCE_MIN_PUBLISHERS = 2
    ABSENCE_ATTACK_STEP = 0.02   # per unavailable/suspended player (doubtful counts half)
    ABSENCE_DEFENCE_STEP = 0.01
    ABSENCE_ATTACK_BOUNDS = (0.92, 1.0)
    ABSENCE_DEFENCE_BOUNDS = (1.0, 1.05)
    ABSENCE_WEIGHTS = (("unavailable", 1.0), ("suspended", 1.0), ("doubtful", 0.5))

    @classmethod
    def from_db(cls, db_path: str, match_id: int, run_id: int, cutoff: str) -> Dict[str, Dict[str, Any]]:
        result = {"home_context": {}, "away_context": {}, "match_context": {}}
        try:
            with sqlite3.connect(db_path) as conn:
                conn.row_factory = sqlite3.Row
                match = conn.execute("SELECT home_team_id, away_team_id FROM matches WHERE id=?", (int(match_id),)).fetchone()
                run = conn.execute("SELECT run_id FROM runs WHERE id=?", (int(run_id),)).fetchone()
                if not match or not run:
                    return result
                for side, team_id in (("home", match["home_team_id"]), ("away", match["away_team_id"])):
                    row = conn.execute(
                        "SELECT profile_json FROM team_profile_snapshots WHERE team_id=? AND data_cutoff_at<=? ORDER BY data_cutoff_at DESC, id DESC LIMIT 1",
                        (team_id, cutoff),
                    ).fetchone()
                    payload = json.loads(row["profile_json"]) if row else {}
                    facts = cls._facts(payload)
                    context = cls._team_context(facts)
                    context.update(cls._absence_context(payload, cutoff))
                    result[f"{side}_context"] = context
                row = conn.execute("SELECT context_json FROM match_context_snapshots WHERE match_id=? AND run_id=?", (int(match_id), str(run["run_id"]))).fetchone()
                result["match_context"] = cls._match_context(cls._facts(json.loads(row["context_json"]) if row else {}))
        except (sqlite3.Error, TypeError, ValueError, json.JSONDecodeError):
            return result
        return result

    @staticmethod
    def _facts(payload: Dict[str, Any]) -> list[str]:
        facts = payload.get("facts", []) if isinstance(payload, dict) else []
        if not facts and isinstance(payload, dict):
            facts = payload.get("head_to_head_facts", [])
        return [str(f.get("value", "")) for f in facts if isinstance(f, dict) and f.get("value")]

    @staticmethod
    def _parse_dt(value: Any) -> Optional[datetime]:
        if not value:
            return None
        try:
            dt = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
        except ValueError:
            return None
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)

    @staticmethod
    def _publisher(url: Any) -> str:
        host = urlparse(str(url or "")).netloc.lower()
        return host[4:] if host.startswith("www.") else host

    @classmethod
    def _absence_context(cls, payload: Dict[str, Any], cutoff: str) -> Dict[str, Any]:
        """Bounded attack/defence multipliers from verified absence claims; empty without claims."""
        cutoff_dt = cls._parse_dt(cutoff)
        facts = payload.get("facts", []) if isinstance(payload, dict) else []
        if cutoff_dt is None or not isinstance(facts, list):
            return {}
        players: Dict[str, float] = {}
        for fact in facts:
            if not isinstance(fact, dict) or fact.get("predicate") != "availability_status":
                continue
            fact_dt = cls._parse_dt(fact.get("source_date"))
            if fact_dt is None or fact_dt > cutoff_dt:
                continue  # cutoff se nikdy neodvozuje; bez data zdroje claim nepoužijeme
            evidence = [e for e in fact.get("evidence") or [] if isinstance(e, dict)]
            if any((cls._parse_dt(e.get("published_at")) or fact_dt) > cutoff_dt for e in evidence):
                continue
            publishers = {cls._publisher(e.get("source_url")) for e in evidence} - {""}
            if len(publishers) < cls.ABSENCE_MIN_PUBLISHERS:
                continue
            value = str(fact.get("value") or "")
            name, _, status = value.rpartition(":")
            weight = next((w for key, w in cls.ABSENCE_WEIGHTS if key in status.lower()), 0.0)
            if not name.strip() or weight <= 0:
                continue
            key = name.strip().lower()
            players[key] = max(players.get(key, 0.0), weight)
        if not players:
            return {}
        total = sum(players.values())
        a_lo, a_hi = cls.ABSENCE_ATTACK_BOUNDS
        d_lo, d_hi = cls.ABSENCE_DEFENCE_BOUNDS
        return {
            "attack_multiplier": round(max(a_lo, min(a_hi, 1.0 - cls.ABSENCE_ATTACK_STEP * total)), 4),
            "defence_multiplier": round(max(d_lo, min(d_hi, 1.0 + cls.ABSENCE_DEFENCE_STEP * total)), 4),
            "absences_counted": len(players),
        }

    @classmethod
    def _team_context(cls, facts: list[str]) -> Dict[str, Any]:
        text = " ".join(facts).lower()
        context: Dict[str, Any] = {}
        if any(term in text for term in cls.FATIGUE_TERMS):
            context["fatigue"] = 0.35
        if any(term in text for term in cls.MOTIVATION_TERMS):
            context["motivation"] = 0.65
        return context

    @classmethod
    def _match_context(cls, facts: list[str]) -> Dict[str, Any]:
        text = " ".join(facts).lower()
        context: Dict[str, Any] = {}
        if re.search(r"\b(derby|rivalry|rivalita)\b", text):
            context["rivalry"] = 0.5
        if any(term in text for term in ("storm", "heavy rain", "snow", "strong wind", "bouře", "sníh")):
            context["weather_severity"] = 0.5
        if any(term in text for term in ("open game", "transition", "counter attack", "high press", "útočný")):
            context["style_goal_factor"] = 1.05
        elif any(term in text for term in ("low block", "defensive", "deep defending", "obranný")):
            context["style_goal_factor"] = 0.95
        return context
