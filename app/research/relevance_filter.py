"""Relevance filtr dokumentů a vět (TODO 11.21).

Důvěryhodnost zdroje neříká nic o tom, zda text je o správném klubu. Víceznačné názvy klubů
(Sparta, Slavia, Dukla, Baník, Slovan…) jinak přivedou do claimů starověké Řecko, hotely,
nizozemské články o Spartě Rotterdam nebo metadata YouTube. Pravidla jsou čistě deterministická
a fail-closed: u víceznačného názvu bez opory ve fotbalovém kontextu se dokument zahodí.
"""
from __future__ import annotations

import unicodedata
from typing import Iterable


def _fold(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    return "".join(c for c in text if not unicodedata.combining(c)).lower()


# Samostatné slovo, které samo o sobě klub neidentifikuje (město/historie/jiný klub se stejným názvem).
AMBIGUOUS_TOKENS = frozenset({
    "sparta", "slavia", "dukla", "banik", "slovan", "bohemians", "spartak", "viktoria", "praha", "prague",
})

# Fotbalový kontext (bez diakritiky). Záměrně ne anglické „league“ (Peloponnesian League).
FOOTBALL_CONTEXT = (
    "fotbal", "football", "soccer", "zapas", "utkani", "trener", "goly", "chance liga", "fortuna liga",
    "fortuna:liga", "1. liga", "first league", "synot liga", "gambrinus", "uefa", "conference league",
    "europa league", "kickoff", "ac sparta", "sk slavia",
)

# Starověká historie: dokument s dvěma a více různými značkami není o klubu.
ANCIENT_MARKERS = (
    "helot", "spartiate", "peloponnes", "lacedaemon", "laconia", "messenia", "hoplit", "thermopyl",
    "athens", "thebes", "corinth", "persia", " bce", " b.c.", "ancient greece", "city-state", "perioikoi",
    "emperor augustus", "historic sites", "historical sites",
)

# Jednoznačné značky starověku: stačí jedna ve větě (názvy měst jako Athens sem nepatří – hrají se tam zápasy).
STRONG_ANCIENT_MARKERS = (
    "helot", "spartiate", "peloponnes", "lacedaemon", "laconia", "hoplit", "thermopyl", "perioikoi", " bce",
)

# Řetězce UI / metadat, které nejsou obsahem článku.
BOILERPLATE_MARKERS = (
    "mix (", "geluid aanzet", "geluid uitzetten", "youtube", " sign in ", " log in ", "all rights reserved",
    "privacy policy", "terms of use", "skip to content", "skip to main", "share this", "follow us",
    "subscribe", "cookie", "newsletter", "přihlásit", "prihlasit", "©", "&nbsp", "views •", "watch later",
)


def is_ambiguous_form(form: str) -> bool:
    """True pro jednoslovný tvar, který klub jednoznačně neidentifikuje (např. „sparta“)."""
    tokens = str(form or "").split()
    return len(tokens) == 1 and tokens[0] in AMBIGUOUS_TOKENS


def ancient_marker_count(folded_text: str) -> int:
    return sum(1 for marker in ANCIENT_MARKERS if marker in folded_text)


def has_football_context(folded_text: str) -> bool:
    return any(marker in folded_text for marker in FOOTBALL_CONTEXT)


def document_mentions_entity(haystack: str, forms: Iterable[str]) -> bool:
    """Je dokument o klubu z úkolu?

    Jednoznačný tvar (např. „sparta praha“, „slovacko“) stačí. Jen víceznačný tvar („sparta“)
    projde, jen když je ve fotbalovém kontextu a text není o starověké historii.
    """
    folded = _fold(haystack)
    matched = [f for f in forms if f and f in folded]
    if not matched:
        return False
    if any(not is_ambiguous_form(f) for f in matched):
        return True
    if ancient_marker_count(folded) >= 2:
        return False
    return has_football_context(folded)


def is_boilerplate_sentence(sentence: str) -> bool:
    low = f" {str(sentence or '').lower()} "
    return any(marker in low for marker in BOILERPLATE_MARKERS)


def is_ancient_history_sentence(sentence: str) -> bool:
    low = _fold(sentence)
    return any(marker in low for marker in STRONG_ANCIENT_MARKERS)


def sentence_is_relevant(sentence: str) -> bool:
    """Věta není UI šum ani starověká historie."""
    return not (is_boilerplate_sentence(sentence) or is_ancient_history_sentence(sentence))
