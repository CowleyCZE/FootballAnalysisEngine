"""Relevance filtr dokumentů a vět (TODO 11.21).

Důvěryhodnost zdroje neříká nic o tom, zda text je o správném klubu. Víceznačné názvy klubů
(Sparta, Slavia, Dukla, Baník, Slovan…) jinak přivedou do claimů starověké Řecko, hotely,
nizozemské články o Spartě Rotterdam nebo metadata YouTube. Pravidla jsou čistě deterministická
a fail-closed: u víceznačného názvu bez opory ve fotbalovém kontextu se dokument zahodí.
"""
from __future__ import annotations

import re
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
    # České souhlasy/reklama/UI a sázkové kurzy (běh M943: souhlas s reklamou měl důvěryhodnost 0,90).
    "potrebujeme vedet", "potřebujeme vědět", "zobrazovat reklamu", "nastavení soukromí", "nastaveni soukromi",
    "souhlas se zpracováním", "souhlas se zpracovanim", "přidat soutěž do záložek", "pridat soutez do zalozek",
    "match odds", "bet365", "\ufffd", "cílené reklamy", "cilene reklamy", "souhlas se zobrazov", "vyberte prosím znovu",
    # Běh M976 (RIVALRY): YouTube metadata (nizozemsky/česky), navigace webu, sázkové návody, seznamy zemí.
    "weergaven", "geleden", "nagesynchroniseerd", "zhlédnutí", "zhlednuti", "přeskočit na obsah",
    "preskocit na obsah", "obchodní podmínky", "obchodni podminky", "ochrana soukromí", "ochrana soukromi",
    "bookmaker", "vip predictions", "cards quick guide", "jupiler pro league", "bosnia and herzegovina",
    # Běh M976_fe22 (RIVALRY): přihlašovací formulář, seznam zemí, anglické sázkové návody o kartách.
    "zapomenuté heslo", "zapomenute heslo", "nemám účet", "nemam ucet", "registrovat", "přihlášení", "prihlaseni",
    "antigua", "dominican republic", "betting", "over/under", "over vs under", "cards picks", "cards count",
    "card counts", "both teams' cards", "booking", "or more cards", "fewer cards", "yellow/red cards",
    "yellow and red cards", "cards shown", "total corners", "which fixtures produce", "lenient-referee",
    # Běh M976_5ca7 (RIVALRY): přehrávač videa, vyhledávání v e-shopu, bonusy sázkovek, Wikipedie (reference), statistiky/tipy.
    "probeer het later", "volledige video", "nalezeno v produktech", "nalezeno v kategori", "free bet", "applepay",
    "banker pick", "stats & predictions", " ppg", "retrieved from", "unsourced material", "find sources",
    "yellow & red cards", "↑ \"", "↑ “",
    # Běh M976_1b8d: e-shop („Zobrazit všechny v produktech … +420 …“), tipy zdarma.
    "zobrazit všechny v", "zobrazit vsechny v", "free football tips", "free horse racing",
    # Běh M976_a388 (GENERAL): rozpisy mládežnických soutvědí, embed videa.
    "liga dorostu", "ligy dorostu", "mládež", "mladez", "<iframe", "připravujeme", "pripravujeme", "akademie",
    # Běh M976_e7ab (GENERAL): šablonové nadpisy a výplňové věty statistických portálů bez faktického obsahu.
    "home/away", "standings & table", "standings and table", "lineups & formations", "let's see how",
    "plenty of action", "club world cup", "(over 2.5)", "(clean sheet)",
    # Běh M976_1101 (RIVALRY): sázkové nabídky; `play_fill` = teaser/odkazový widget denik.cz (titulky jiných článků, ne obsah).
    "bet builder", "accumulator tips", "super boosts", "play_fill",
    # Běh M976_9ae1 (RIVALRY): nizozemské „související reels“ (hooligans.cz), promáčková lišta tipů/aplikace,
    # okresní soutěže a „sedmá liga“ (nesouvisející článek o amatérovi s důvěryhodností 0,90).
    "gerelateerde reels", "hooligans.cz", "dark horse tips", "download our app", "news & predictions",
    "sedmou ligu", "sedmé ligy", "sedmé lize", "okresní přebor", "okresního přeboru", "okresní soutěž",
    # Běh M976_3595 (RIVALRY): lišta „Premium Horse Racing Tips / Elite Value Tips“ (0,39) a hlavička widgetu zápasu
    # („… 2:00 PM UTCFollowmatches1. Liga Round 14Follow…“, 0,62) – navigace portálu, ne tvrzení.
    "horse racing tips", "elite value tips", "premium football tips", "utcfollow", "followmatches", "round 14follow",
    # Běh M976_9599 (RIVALRY): reklama tipsterů a šablonový text widgetu zápasu.
    "staking plan", "tipman", "you can check the recent head-to-head",
    # Běh M976_d844 (RIVALRY): český seznam zemí z výběru jazyka/regionu (0,49) a widget „Free.Follow …Follow“.
    "bosna a hercegovina", "dominikánská republika", "dominikanska republika", "free.follow",
    # Běh M976_6f8d (RIVALRY): reklama premium předplatného tipsterů (REJECTED, ale pro jistotu i jako šum).
    "unblurs", "verified win rate", "upgrade to premium",
)

# Slovník šablonových nadpisů statistických portálů („Scoring Consistency“, „Recent Form Home/Away“…).
# Věta složená jen z těchto slov (min. 2) je nadpis sekce, ne tvrzení.
_STATS_HEADING_WORDS = frozenset({
    "scoring", "consistency", "goal", "goals", "trends", "trend", "defensive", "attacking", "record", "recent",
    "form", "clean", "sheet", "sheets", "home", "away", "standings", "table", "lineups", "lineup", "formations",
    "starting", "head", "to", "over", "under", "statistics", "stats", "results", "overall", "and", "&", "/",
})


# Země z rozbalovacích seznamů výběru jazyka/regionu (běh M976_6f8d: „Chance Národní Liga Jihoafrická republika Pobřeží slonoviny“).
# Věta, která jich obsahuje 2 a více, je menu, ne tvrzení o zápase (porovnává se bez diakritiky).
_COUNTRY_NAMES = (
    "bosna a hercegovina", "dominikanska republika", "jihoafricka republika", "pobrezi slonoviny",
    "spojene arabske emiraty", "saudska arabie", "novy zeland", "kostarika", "antigua", "trinidad",
    "severni makedonie", "stredoafricka republika", "zeleny predhori", "papua", "burkina faso",
)


def _is_country_list(sentence: str) -> bool:
    folded = _fold(sentence)
    return sum(1 for name in _COUNTRY_NAMES if name in folded) >= 2


def _is_social_link_list(low: str) -> bool:
    """Věta tvořená odkazy na sociální sítě („Facebook ... Instagram ...“) není obsah."""
    return sum(1 for name in ("facebook", "instagram", "twitter", "tiktok", "youtube") if name in low) >= 2


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


# Zkratky záhlaví tabulek (Pld W D L GF GA GD Pts…): 4 a více různých v jedné větě = tabulka, ne tvrzení.
_TABLE_HEADER_ABBREVIATIONS = frozenset({"pld", "w", "d", "l", "gf", "ga", "gd", "pts", "ppg", "mp", "gp"})
_LETTERS_GLUED_TO_DIGITS = re.compile(r"[^\W\d_]{3,}\d{5,}")  # „Form603361“
_TIME_GLUED_TO_LETTERS = re.compile(r"\d:\d{2}[^\W\d_]")  # „13:15VIKTORIA“ (rozpis zápasů bez mezer)


def _has_glued_table_token(sentence: str) -> bool:
    """Slepený tabulkový/menu text („StatisticsPldWDLGFGAGDPPGLast“, „SlováckoDerbyFC ZlínFotbal…“, „Form603361“):
    dlouhý token bez mezer s vysokým podílem velkých písmen, token s ≥ 3 přechody malé→velké písmeno nebo písmena
    slepená s dlouhou řadou číslic. Běžná česká slova takový tvar nemají."""
    for token in str(sentence or "").split():
        letters = [c for c in token if c.isalpha()]
        if len(token) >= 20 and letters and sum(c.isupper() for c in letters) / len(letters) >= 0.3:
            return True
        if len(token) >= 14 and sum(1 for a, b in zip(token, token[1:]) if a.islower() and b.isupper()) >= 3:
            return True
        if _LETTERS_GLUED_TO_DIGITS.search(token) or _TIME_GLUED_TO_LETTERS.search(token):
            return True
    return False


def _is_table_header(sentence: str) -> bool:
    tokens = {t.strip(".,;:()|/").lower() for t in str(sentence or "").split()}
    return len(tokens & _TABLE_HEADER_ABBREVIATIONS) >= 4


def is_table_noise(text: str) -> bool:
    """Tabulkový šum (slepená záhlaví/čísla, řada zkratek Pld W D L GF GA…). Použitelné i na text claimu."""
    return _has_glued_table_token(text) or _is_table_header(text)


def _is_fixture_label(sentence: str) -> bool:
    """Krátký popisek zápasu („Millwall vs Derby“, „Leeds United U18 vs Derby County U18“) není tvrzení."""
    low = f" {str(sentence or '').lower()} "
    has_result = re.search(r"\d+\s*[:\-–]\s*\d+", low) is not None  # „Zlín vs Slovácko skončilo 2:1“ je tvrzení
    return (" vs " in low or " vs. " in low) and len(low.split()) <= 8 and not has_result


def _is_stats_heading(sentence: str) -> bool:
    """Nadpis sekce statistického portálu složený jen z šablonových slov („Scoring Consistency Home/Away“)."""
    words = [w for w in re.split(r"[\s/()|:,.\-]+", str(sentence or "").lower()) if w]
    return len(words) >= 2 and all(w in _STATS_HEADING_WORDS for w in words)


def is_boilerplate_sentence(sentence: str) -> bool:
    low = f" {str(sentence or '').lower()} "
    return (_is_social_link_list(low) or _is_fixture_label(sentence) or is_table_noise(sentence)
            or _is_stats_heading(sentence) or _is_country_list(sentence)
            or any(marker in low for marker in BOILERPLATE_MARKERS))


def is_ancient_history_sentence(sentence: str) -> bool:
    low = _fold(sentence)
    return any(marker in low for marker in STRONG_ANCIENT_MARKERS)


def sentence_is_relevant(sentence: str) -> bool:
    """Věta není UI šum ani starověká historie."""
    return not (is_boilerplate_sentence(sentence) or is_ancient_history_sentence(sentence))
