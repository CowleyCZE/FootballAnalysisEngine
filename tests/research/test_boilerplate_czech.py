"""Šum z běhu M943: souhlas s reklamou, odkazy na sociální sítě, rozbité kódování, sázkové kurzy."""
import pytest

from app.research.relevance_filter import sentence_is_relevant


@pytest.mark.parametrize("sentence", [
    "Abyste mohli pokračovat, potřebujeme vědět, jakou formou vám můžeme zobrazovat reklamu",
    "Facebook p\ufffd\ufffdpravky Facebook akademie Instagram p\ufffd\ufffdpravky",
    "Facebook přípravky Instagram akademie",
    "Match oddsBet365Full-time12.40X3.25",
    "Česko - Chance Liga 2025/2026 Přidat soutěž do záložek",
])
def test_boilerplate_is_dropped(sentence):
    assert not sentence_is_relevant(sentence)


@pytest.mark.parametrize("sentence", [
    "Slovácko v neděli přivítá Teplice a chce navázat na výhru z minulého kola.",
    "Teplice mají v kádru tři zraněné hráče, trenér počítá se základní sestavou.",
])
def test_football_content_is_kept(sentence):
    assert sentence_is_relevant(sentence)


def test_fallback_fragment_never_contains_boilerplate():
    from app.research.evidence_extractor import EvidenceExtractor
    doc = {"url": "https://example.cz/a", "title": "Slovácko Teplice",
           "text": "Abyste mohli pokračovat, potřebujeme vědět, jakou formou vám můžeme zobrazovat reklamu.\n"
                   "Facebook přípravky Facebook akademie Instagram přípravky\n"
                   "Slovácko přivítá v sobotu Teplice na domovám stadionu."}
    items = EvidenceExtractor().extract_evidence(doc, "STYLE_MATCHUP", entities=["Slovácko", "FK Teplice"])
    joined = " ".join(e.text_fragment for e in items).lower()
    assert "reklamu" not in joined and "instagram" not in joined
