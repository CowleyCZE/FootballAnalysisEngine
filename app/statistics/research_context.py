"""Map cited research snapshots to bounded predictor context values.

The mapper is deliberately conservative: it only emits a correction when a
stored, validated claim contains explicit contextual terms. Missing or vague
research remains missing rather than being guessed.
"""
from __future__ import annotations

import json
import re
import sqlite3
import unicodedata
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse


def _fold(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    return "".join(c for c in text if not unicodedata.combining(c)).lower()


_CLUB_PREFIXES = frozenset({"sk", "fc", "fk", "ac", "mfk", "sc", "1", "tj"})


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

    # Kontext z textu (únava, motivace, rivalita, styl): jen ověřené claimy (TODO 11.32). Claim musí mít dostačující
    # důvěryhodnost a text musí zmiňovat správný tým (rivalita: oba týmy). Klíčová slova se hledají jako celá slova
    # bez diakritiky, aby „derby“ z článku o jiném klubu nebo „travel“ uvnitř jiného slova neměnily model.
    MIN_CONTEXT_CONFIDENCE = 0.5
    STYLE_MIN_VOTE_MARGIN = 2
    _FATIGUE_RE = re.compile(r"\b(fatigue|fixture congestion|short rest|rest days|travell?\w*|rotation|unav\w*|odpocin\w*|cestov\w*)\b")
    _MOTIVATION_RE = re.compile(r"\b(must win|qualification|relegation|title race|objectives?|motiv\w*|playoff|postup\w*|sestup\w*)\b")
    _RIVALRY_RE = re.compile(r"\b(derby|rivalry|rivalita)\b")
    _OPEN_STYLE_RE = re.compile(r"\b(open game|transitions?|counter[- ]attack\w*|high press\w*|utocny)\b")
    _DEFENSIVE_STYLE_RE = re.compile(r"\b(low block|defensive(?! line)|deep defending|obranny)\b")

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
                names: Dict[str, str] = {}
                for side, team_id in (("home", match["home_team_id"]), ("away", match["away_team_id"])):
                    name_row = conn.execute("SELECT name FROM teams WHERE id=?", (team_id,)).fetchone()
                    names[side] = str(name_row["name"]) if name_row and name_row["name"] else ""
                for side, team_id in (("home", match["home_team_id"]), ("away", match["away_team_id"])):
                    row = conn.execute(
                        "SELECT profile_json FROM team_profile_snapshots WHERE team_id=? AND data_cutoff_at<=? ORDER BY data_cutoff_at DESC, id DESC LIMIT 1",
                        (team_id, cutoff),
                    ).fetchone()
                    payload = json.loads(row["profile_json"]) if row else {}
                    context = cls._team_context(cls._verified_texts(cls._records(payload), [names[side]]))
                    context.update(cls._absence_context(payload, cutoff))
                    result[f"{side}_context"] = context
                row = conn.execute("SELECT context_json FROM match_context_snapshots WHERE match_id=? AND run_id=?", (int(match_id), str(run["run_id"]))).fetchone()
                result["match_context"] = cls._match_context_from_records(
                    cls._records(json.loads(row["context_json"]) if row else {}), names["home"], names["away"])
        except (sqlite3.Error, TypeError, ValueError, json.JSONDecodeError):
            return result
        return result

    @staticmethod
    def _records(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        facts = payload.get("facts", []) if isinstance(payload, dict) else []
        if not facts and isinstance(payload, dict):
            facts = payload.get("head_to_head_facts", [])
        return [f for f in facts if isinstance(f, dict) and f.get("value")]

    @staticmethod
    def _key_word(team_name: str) -> str:
        """Rozlišující slovo klubu bez předpon („SK Artis Brno“ → „artis“, „Bohemians 1905“ → „bohemians“)."""
        for token in re.split(r"[^a-z0-9]+", _fold(team_name)):
            if token and token not in _CLUB_PREFIXES and len(token) >= 4:
                return token
        return _fold(team_name).strip()

    @classmethod
    def _mentions(cls, text: str, team_name: str) -> bool:
        key = cls._key_word(team_name)
        return bool(key) and re.search(rf"\b{re.escape(key)}", _fold(text)) is not None

    @classmethod
    def _confident(cls, record: Dict[str, Any]) -> bool:
        try:
            return float(record.get("confidence")) >= cls.MIN_CONTEXT_CONFIDENCE
        except (TypeError, ValueError):
            return False

    @classmethod
    def _verified_texts(cls, records: List[Dict[str, Any]], teams: List[str]) -> List[str]:
        """Texty claimů s dostatečnou důvěryhodností, které zmiňují (aspoň jeden z) dané týmy."""
        names = [t for t in teams if t]
        return [str(r["value"]) for r in records
                if cls._confident(r) and names and any(cls._mentions(str(r["value"]), n) for n in names)]

    @classmethod
    def _match_context_from_records(cls, records: List[Dict[str, Any]], home: str, away: str) -> Dict[str, Any]:
        context: Dict[str, Any] = {}
        if not home or not away:
            return context
        rivalry_texts, style_texts = [], []
        for r in records:
            if not cls._confident(r):
                continue
            text = str(r["value"])
            domain = str(r.get("domain") or "").upper()
            predicate = str(r.get("predicate") or "").lower()
            if (domain == "RIVALRY" or "rivalry" in predicate) and cls._mentions(text, home) and cls._mentions(text, away):
                rivalry_texts.append(text)
            if (domain == "STYLE_MATCHUP" or "style" in predicate) and (cls._mentions(text, home) or cls._mentions(text, away)):
                style_texts.append(text)
        if any(cls._RIVALRY_RE.search(_fold(t)) for t in rivalry_texts):
            context["rivalry"] = 0.5
        open_votes = sum(1 for t in style_texts if cls._OPEN_STYLE_RE.search(_fold(t)))
        defensive_votes = sum(1 for t in style_texts if cls._DEFENSIVE_STYLE_RE.search(_fold(t)))
        if open_votes - defensive_votes >= cls.STYLE_MIN_VOTE_MARGIN:
            context["style_goal_factor"] = 1.05
        elif defensive_votes - open_votes >= cls.STYLE_MIN_VOTE_MARGIN:
            context["style_goal_factor"] = 0.95
        return context

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
        """Texty už jsou předfiltrované (`_verified_texts`): ověřené a týkající se daného týmu."""
        text = _fold(" ".join(facts))
        context: Dict[str, Any] = {}
        if cls._FATIGUE_RE.search(text):
            context["fatigue"] = 0.35
        if cls._MOTIVATION_RE.search(text):
            context["motivation"] = 0.65
        return context

    @classmethod
    def _match_context(cls, facts: list[str]) -> Dict[str, Any]:
        """Zpětně kompatibilní varianta nad holými texty (bez ověření týmů); `from_db` používá
        `_match_context_from_records`."""
        text = _fold(" ".join(facts))
        context: Dict[str, Any] = {}
        if cls._RIVALRY_RE.search(text):
            context["rivalry"] = 0.5
        if cls._OPEN_STYLE_RE.search(text):
            context["style_goal_factor"] = 1.05
        elif cls._DEFENSIVE_STYLE_RE.search(text):
            context["style_goal_factor"] = 0.95
        return context
