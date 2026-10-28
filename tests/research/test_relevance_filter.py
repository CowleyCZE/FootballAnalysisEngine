"""TODO 11.21 – víceznačné názvy klubů a šum (starověká Sparta, YouTube metadata)."""
from app.research.evidence_extractor import EvidenceExtractor
from app.research.relevance_filter import (
    document_mentions_entity, is_ambiguous_form, is_boilerplate_sentence, sentence_is_relevant,
)

SPARTA_FORMS = {"sparta praha", "sparta", "praha"}


def _doc(text, title="", url="https://example.test/a"):
    return {"text": text, "title": title, "url": url, "document_id": 1}


def test_ambiguous_forms():
    assert is_ambiguous_form("sparta") and is_ambiguous_form("slavia")
    assert not is_ambiguous_form("sparta praha") and not is_ambiguous_form("slovacko")


def test_ancient_sparta_document_is_rejected():
    text = ("Sparta was a city-state in Laconia. Helots were enslaved by the Spartiates. "
            "Rivalry with Athens and Thebes marked the Peloponnesian War, 480 BCE.")
    assert not document_mentions_entity(text, SPARTA_FORMS)


def test_ambiguous_name_without_football_context_is_rejected():
    assert not document_mentions_entity("Hotel Sparta nabízí ubytování v centru města.", SPARTA_FORMS)


def test_ambiguous_name_with_football_context_passes():
    assert document_mentions_entity("Sparta vyhrála fotbalový zápas 2:0.", SPARTA_FORMS)


def test_distinctive_form_passes_without_extra_context():
    assert document_mentions_entity("Sparta Praha má nového trenéra.", SPARTA_FORMS)


def test_boilerplate_sentences():
    assert is_boilerplate_sentence("Mix (50+) - YouTube")
    assert is_boilerplate_sentence("Geluid aanzet voor Sparta Rotterdam")
    assert not sentence_is_relevant("Helots made up the vast majority of the population in Laconia.")
    assert sentence_is_relevant("Sparta Praha porazila Slovácko 2:0.")
    assert sentence_is_relevant("Zápas se hraje v Athens, Georgia.")


def test_extractor_drops_ancient_history_document():
    text = ("Sparta rivalry with Athens was bitter. The helots revolted against Sparta in 464 BCE. "
            "Spartiates held full rights in Laconia.")
    assert EvidenceExtractor().extract_evidence(_doc(text), "RIVALRY", entities=["Sparta Praha", "Slovácko"]) == []


def test_extractor_keeps_football_sentences_and_drops_boilerplate():
    text = ("Sparta Praha a Slovácko se utkají v derby fotbalové Chance Ligy.\n"
            "Mix (50+) - YouTube přihlásit odběr.")
    ev = EvidenceExtractor().extract_evidence(_doc(text), "RIVALRY", entities=["Sparta Praha", "Slovácko"])
    assert [e.text_fragment for e in ev] == ["Sparta Praha a Slovácko se utkají v derby fotbalové Chance Ligy."]
