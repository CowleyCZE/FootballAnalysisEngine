"""TODO 12.2 – cizojazyčný právní/sázkový balast (fr/es/nl) se u domácí ligy ignoruje."""
import pytest

from app.research.evidence_extractor import EvidenceExtractor
from app.research.relevance_filter import (
    detect_foreign_language, is_boilerplate_sentence, is_foreign_language_noise, sentence_is_relevant,
)

FR = "Les jeux d’argent et de hasard peuvent être dangereux : isolement, endettement, dépendance."
ES = "Los juegos de azar pueden ser adictivos y no son aptos para menores de edad en este país."
NL = "Gokken kan verslavend zijn en het is niet toegestaan voor minderjarigen in dit land."


@pytest.mark.parametrize("text,lang", [(FR, "fr"), (ES, "es"), (NL, "nl")])
def test_foreign_language_detected(text, lang):
    assert detect_foreign_language(text) == lang
    assert is_foreign_language_noise(text, "Chance Liga")
    assert not sentence_is_relevant(text, "Chance Liga")


@pytest.mark.parametrize("text", [
    "Artis Brno v sobotu přivítá Bohemians a trenér Kozel počítá s plnou sestavou.",
    "Bohemians will host Artis Brno on Saturday and the coach expects a full squad for the match.",
    "Eden Hazard se vrátil po zranění a nastoupí v základní sestavě.",
])
def test_czech_and_english_are_not_foreign(text):
    assert detect_foreign_language(text) is None
    assert sentence_is_relevant(text, "Chance Liga")


def test_international_cup_keeps_foreign_text():
    assert not is_foreign_language_noise(FR, "UEFA Conference League")
    assert not is_foreign_language_noise(NL, "Evropské poháry")


def test_gambling_legal_phrases_are_boilerplate():
    assert is_boilerplate_sentence("Les jeux d’argent et de hasard peuvent être dangereux")
    assert is_boilerplate_sentence("Please gamble responsibly and set your limits before you play.")
    assert not is_boilerplate_sentence("Eden Hazard hrál za Chelsea a Real Madrid.")


def test_extractor_drops_french_paragraph_for_domestic_league():
    doc = {"url": "https://example.cz/a", "title": "Artis Brno – Bohemians",
           "text": f"Artis Brno přivítá Bohemians a trenér chce výhru v ligovém zápase. {FR}"}
    ev = EvidenceExtractor().extract_evidence(doc, "GENERAL", entities=["Artis Brno", "Bohemians 1905"],
                                              competition="Chance Liga")
    joined = " ".join(e.text_fragment for e in ev)
    assert "jeux" not in joined
