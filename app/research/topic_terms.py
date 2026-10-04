from __future__ import annotations

from typing import Dict, List


DOMAIN_TOPIC_TERMS: Dict[str, List[str]] = {
    "MATCH_IDENTITY": [
        "fixture",
        "match",
        "official",
        "stadium",
        "venue",
        "kickoff",
        "date",
    ],
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
}


def get_topic_terms(domain: str) -> List[str]:
    """
    Return deterministic relevance terms for a research domain.

    Unknown domains intentionally return an empty list rather than guessing
    topic semantics.
    """
    return list(DOMAIN_TOPIC_TERMS.get(domain, []))
