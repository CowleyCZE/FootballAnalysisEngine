from __future__ import annotations

from typing import Dict, List


DOMAIN_TOPIC_TERMS: Dict[str, List[str]] = {
    "TEAM_PROFILE_HOME": ["injury", "suspension", "league table", "standings", "form", "results", "xg", "home record", "tactics", "manager", "zranění", "tabulka", "forma"],
    "TEAM_PROFILE_AWAY": ["injury", "suspension", "league table", "standings", "form", "results", "xg", "away record", "tactics", "manager", "zranění", "tabulka", "forma"],
    "HEAD_TO_HEAD": ["head to head", "previous meetings", "h2h", "derby", "rivalry", "vzájemné zápasy", "rivalita"],
    "RECENT_FORM": [
        "result",
        "results",
        "match",
        "matches",
        "win",
        "draw",
        "loss",
        "form",
        "score",
    ],
    "ABSENCES_HOME": [
        "injury",
        "injuries",
        "injured",
        "absence",
        "absent",
        "unavailable",
        "suspended",
        "suspension",
        "zranění",
        "absence",
        "zraněný",
        "suspendace",
    ],
    "ABSENCES_AWAY": [
        "injury",
        "injuries",
        "injured",
        "absence",
        "absent",
        "unavailable",
        "suspended",
        "suspension",
        "zranění",
        "absence",
        "zraněný",
        "suspendace",
    ],
    "WEATHER": [
        "weather",
        "forecast",
        "temperature",
        "wind",
        "rain",
        "snow",
        "humidity",
        "počasí",
        "předpověď",
        "teplota",
        "vítr",
        "déšť",
        "sníh",
    ],
    "REFEREE": ["referee", "official", "cards", "fouls", "penalties", "rozhodčí", "karty", "fauly", "penalty"],
    "RIVALRY": ["derby", "rivalry", "intensity", "cards", "rivalita", "derby", "historie"],
    "STYLE_MATCHUP": ["tactical", "tactics", "pressing", "possession", "transition", "counter", "set pieces", "styl", "taktika"],
    "MOTIVATION_HOME": ["table", "position", "qualification", "relegation", "objective", "rotation", "motivation", "tabulka", "motivace"],
    "MOTIVATION_AWAY": ["table", "position", "qualification", "relegation", "objective", "rotation", "motivation", "tabulka", "motivace"],
    "TRAVEL_FATIGUE_HOME": ["fixture congestion", "rest days", "travel", "rotation", "fatigue", "schedule", "odpočinek", "únava", "cestování"],
    "TRAVEL_FATIGUE_AWAY": ["fixture congestion", "rest days", "travel", "rotation", "fatigue", "schedule", "odpočinek", "únava", "cestování"],
}


def get_topic_terms(domain: str) -> List[str]:
    """
    Return deterministic relevance terms for a research domain.

    Unknown domains intentionally return an empty list rather than guessing
    topic semantics.
    """
    return list(DOMAIN_TOPIC_TERMS.get(domain, []))
