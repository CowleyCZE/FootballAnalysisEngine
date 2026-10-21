"""TODO 3.4 – čeština v extrakci, claimech a dotazech."""
from datetime import datetime
from types import SimpleNamespace

from app.research.claim_builder import ClaimBuilder, NAME_RE
from app.research.evidence_extractor import EvidenceExtractor, keywords_for_domain
from app.research.models import AbsenceStatus
from app.research.query_builder import QueryBuilder


def _doc(text):
    return {"text": text, "url": "https://example.cz/a", "document_id": 1}


def test_czech_names_with_diacritics_are_found():
    names = NAME_RE.findall("Zraněný je Tomáš Chorý a také Ladislav Šimůnek.")
    assert "Tomáš Chorý" in names
    assert "Ladislav Šimůnek" in names


def test_czech_absence_sentence_is_extracted_and_classified():
    text = "Podle trenéra je obránce Ladislav Krejčí zraněn a v neděli nenastoupí. Počasí bude slunečné a teplé."
    ev = EvidenceExtractor().extract_evidence(_doc(text), "ABSENCES_HOME")
    assert len(ev) == 1 and "zraněn" in ev[0].text_fragment
    claims = ClaimBuilder().build_claims_from_evidence(ev, "Sparta Praha")
    assert claims[0].subject == "Ladislav Krejčí"
    assert claims[0].object_value == AbsenceStatus.UNAVAILABLE.value


def test_czech_doubt_and_suspension_status():
    cb = ClaimBuilder()
    ev = EvidenceExtractor().extract_evidence(_doc("Start Václava Černého je otázný kvůli svalu."), "ABSENCES_AWAY")
    assert cb.build_claims_from_evidence(ev, "Slavia Praha")[0].object_value == AbsenceStatus.DOUBTFUL.value
    ev = EvidenceExtractor().extract_evidence(_doc("Jan Kuchta musí na distanc kvůli červeným kartám."), "ABSENCES_AWAY")
    assert cb.build_claims_from_evidence(ev, "Slavia Praha")[0].object_value == AbsenceStatus.SUSPENDED.value


def test_czech_keywords_for_other_domains():
    assert any("počasí" in w for w in keywords_for_domain("WEATHER"))
    assert any("rozhodčí" in w for w in keywords_for_domain("REFEREE"))
    assert any("tabulk" in w for w in keywords_for_domain("MOTIVATION_HOME"))
    ev = EvidenceExtractor().extract_evidence(_doc("V neděli bude pršet, předpověď hlásí déšť a silný vítr."), "WEATHER")
    assert ev and "déšť" in ev[0].text_fragment


def test_czech_queries_are_generated():
    task = SimpleNamespace(domain="ABSENCES_HOME", home_team="Sparta Praha", away_team="Slavia Praha",
                           competition="Chance Liga", scheduled_at=datetime(2026, 11, 10, 18, 0), venue="Letná")
    queries = QueryBuilder().build_queries(task)
    texts = [q["query"] for q in queries]
    assert any("zranění" in t for t in texts)
    assert any(q["type"] == "DISCOVERY_CS" for q in queries)
