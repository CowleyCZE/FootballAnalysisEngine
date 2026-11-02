"""Předfiltr výsledků vyhledávání pro zápasové domény bez týmového subjektu (běh M976_e7ab).

`SearchEngine` u dotazu bez `team`/`home_team`/`away_team` (GENERAL, EXPECTED_LINEUPS, RIVALRY, STYLE_MATCHUP,
opravné úkoly) neověřuje identitu vůbec, takže se stahovaly nesouvisející weby (fórum Ford Puma, ...) a spotřebovaly
čas a paměť crawleru. Výsledek musí v titulku, úryvku nebo URL zmínit aspoň jeden ze dvou týmů zápasu
(porovnání bez diakritiky a bez ohledu na velikost písmen). Deterministické, nic se nedomýšlí.
"""
from __future__ import annotations

import os
import re
import unicodedata
from typing import Any, Iterable, List

# Domény, u kterých se zmínka týmu na úrovni výsledku nevyžaduje (rozhodčí je jiný subjekt než tým;
# H2H má vlastní přísnou kontrolu dvou týmů v SearchEngine).
EXEMPT_DOMAINS = frozenset({"REFEREE", "HEAD_TO_HEAD"})

_IGNORED_WORDS = frozenset({"club", "real", "city", "town", "praha", "prague", "united", "sport", "sporting"})


def _fold(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    return "".join(c for c in text if not unicodedata.combining(c)).lower()


def team_forms(name: str) -> List[str]:
    """Tvary názvu týmu pro hledání (bez diakritiky): celé jméno a významná slova (≥ 4 znaky)."""
    folded = _fold(name).strip()
    if not folded:
        return []
    forms = [folded]
    for word in re.split(r"[^a-z0-9]+", folded):
        if len(word) >= 4 and word not in _IGNORED_WORDS and word not in forms:
            forms.append(word)
    return forms


def _result_text(result: Any) -> str:
    if isinstance(result, dict):
        parts = [result.get("title"), result.get("content"), result.get("url")]
    else:
        parts = [getattr(result, "title", ""), getattr(result, "content", ""), getattr(result, "url", "")]
    return _fold(" ".join(str(p or "") for p in parts))


def mentions_any_team(result: Any, teams: Iterable[str]) -> bool:
    text = _result_text(result)
    return any(form in text for team in teams for form in team_forms(team))


def is_enabled() -> bool:
    """Vypnutí pro diagnostiku: `FAE_REQUIRE_TEAM_MENTION=0`."""
    return os.getenv("FAE_REQUIRE_TEAM_MENTION", "1").strip() != "0"


def filter_by_team_mention(results: Iterable[Any], domain: str, home_team: str, away_team: str) -> List[Any]:
    """Ponechá jen výsledky, které zmiňují domácí nebo hostující tým. Bez názvů týmů nebo u vyňatých domén
    se nic nefiltruje."""
    items = list(results or [])
    teams = [t for t in (home_team, away_team) if t and str(t).strip()]
    if not teams or str(domain or "").upper() in EXEMPT_DOMAINS or not is_enabled():
        return items
    return [r for r in items if mentions_any_team(r, teams)]
