"""Map cited research snapshots to bounded predictor context values.

The mapper is deliberately conservative: it only emits a correction when a
stored, validated claim contains explicit contextual terms. Missing or vague
research remains missing rather than being guessed.
"""
from __future__ import annotations

import json
import re
import sqlite3
from typing import Any, Dict


class ResearchContextMapper:
    FATIGUE_TERMS = ("fatigue", "fixture congestion", "short rest", "rest days", "travel", "rotation", "únava", "odpočinek", "cestov")
    MOTIVATION_TERMS = ("must win", "qualification", "relegation", "title race", "objective", "motiv", "playoff", "postup", "sestup")

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
                    facts = cls._facts(json.loads(row["profile_json"]) if row else {})
                    result[f"{side}_context"] = cls._team_context(facts)
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
