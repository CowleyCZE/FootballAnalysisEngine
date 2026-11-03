"""TODO 12.3 \u2013 striktn\u00ed validace rivality/derby (`PAIR_DOMAINS` leak).

Tvrzen\u00ed o derby/rivalit\u011b se p\u0159ij\u00edm\u00e1 jen tehdy, kdy\u017e se v jeho bezprost\u0159edn\u00edm kontextu (fragment d\u016fkazu) vyskytuj\u00ed
OBA konkr\u00e9tn\u00ed soupe\u0159i z \u00fakolu. Pokud text o derby mluv\u00ed, ale druh\u00fdm subjektem je jin\u00fd klub (nap\u0159. Slavia m\u00edsto
Artisu) nebo jde o pojmenovan\u00e9 derby jin\u00e9 dvojice (\u201eVr\u0161ovick\u00e9 derby\u201c), tvrzen\u00ed se zam\u00edtne s `REJECTED_FOREIGN_DERBY`.
\u201eD\u016fkaz\u201c bez zm\u00ednky o derby/rivalit\u011b se zde nehodnot\u00ed.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Iterable, Optional, Set

from app.statistics.history_autofill import ALIASES_FILE, _load_aliases, canonical_team_key, resolve_team_key

REJECTED_FOREIGN_DERBY = "REJECTED_FOREIGN_DERBY"
REJECTED_RIVALRY_PAIR = "REJECTED_RIVALRY_PAIR"

_DERBY_TERMS = ("derby", "rivalit", "rivalry", "rival ")
# Pojmenovan\u00e1 derby konkr\u00e9tn\u00edch dvojic (bez diakritiky) \u2013 bez obou t\u00fdm\u016f v textu nelze potvrdit, \u017ee jde o dvojici z \u00fakolu.
_NAMED_DERBIES = ("vrsovick", "vecne derby", "prazsk", "eternal derby", "moravsk", "slezsk", "vychodocesk")


def _fold(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    return "".join(c for c in text if not unicodedata.combining(c)).lower()


def _team_forms(name: str) -> Set[str]:
    aliases = _load_aliases(str(ALIASES_FILE))
    key = resolve_team_key(name)
    group = {canonical_team_key(name)}
    if key:
        group.add(key)
        group.update(a for a, target in aliases.items() if target == key)
    forms = {f for f in group if f}
    forms.update(t for f in list(forms) for t in f.split() if len(t) >= 5)
    return forms


def _contains_word(folded: str, phrase: str) -> bool:
    return bool(phrase) and re.search(rf"(?<![a-z0-9]){re.escape(phrase)}(?![a-z0-9])", folded) is not None


def _mentions(folded: str, forms: Iterable[str]) -> bool:
    return any(_contains_word(folded, f) for f in forms)


def _other_clubs(own_keys: Set[str]) -> Set[str]:
    """Aliasy a kl\u00ed\u010de klub\u016f z registru, kter\u00e9 nepat\u0159\u00ed ani jednomu z t\u00fdm\u016f \u00fakolu."""
    aliases = _load_aliases(str(ALIASES_FILE))
    names: Set[str] = set()
    for alias, target in aliases.items():
        if target in own_keys:
            continue
        for item in (alias, target):
            item = _fold(item)
            if len(item) >= 5:
                names.add(item)
    return names


def rivalry_rejection_reason(text: str, home_team: str, away_team: str) -> Optional[str]:
    """None = tvrzen\u00ed lze p\u0159ijmout; jinak k\u00f3d d\u016fvodu zam\u00edtnut\u00ed."""
    folded = _fold(text)
    if not any(term in f" {folded} " or term in folded for term in _DERBY_TERMS):
        return None
    home_forms, away_forms = _team_forms(home_team), _team_forms(away_team)
    if _mentions(folded, home_forms) and _mentions(folded, away_forms):
        return None
    own_keys = {k for k in (resolve_team_key(home_team), resolve_team_key(away_team)) if k}
    own_forms = home_forms | away_forms
    other = {c for c in _other_clubs(own_keys) if c not in own_forms and _contains_word(folded, c)}
    if other or any(marker in folded for marker in _NAMED_DERBIES):
        return REJECTED_FOREIGN_DERBY
    return REJECTED_RIVALRY_PAIR
