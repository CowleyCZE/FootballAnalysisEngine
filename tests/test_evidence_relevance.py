from app.research.evidence_extractor import EvidenceExtractor, entity_forms


def _doc(text, title=""):
    return {"text": text, "title": title, "url": "https://example.test/a", "document_id": 1}


def test_irrelevant_document_is_dropped_when_entities_given():
    doc = _doc("Global surface temperature rises with wind and rain in the climate record.")
    assert EvidenceExtractor().extract_evidence(doc, "WEATHER", entities=["Teplice", "Artis Brno"]) == []


def test_relevant_document_keeps_keyword_sentences():
    doc = _doc("Zápas Teplice proti Brnu ovlivní vítr a déšť během večera.", title="Počasí Teplice")
    result = EvidenceExtractor().extract_evidence(doc, "WEATHER", entities=["Teplice", "Artis Brno"])
    assert result and all("Teplice" in e.text_fragment or "vítr" in e.text_fragment for e in result)


def test_alias_matches_zbrojovka():
    forms = entity_forms(["Artis Brno"])
    assert "zbrojovka brno" in forms


def test_evidence_capped_per_document():
    text = " ".join(f"Teplice injury report number {i} confirmed today." for i in range(200))
    result = EvidenceExtractor().extract_evidence(_doc(text), "ABSENCES_HOME", entities=["Teplice"], max_items=10)
    assert len(result) == 10


def test_profile_domain_uses_topic_terms_not_every_sentence():
    text = "Teplice lead the table this season. The stadium café sells coffee and cakes daily."
    result = EvidenceExtractor().extract_evidence(_doc(text), "TEAM_PROFILE_HOME", entities=["Teplice"])
    assert len(result) == 1 and "table" in result[0].text_fragment
