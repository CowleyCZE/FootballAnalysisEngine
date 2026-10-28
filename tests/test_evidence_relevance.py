from app.research.evidence_extractor import EvidenceExtractor, entity_forms


def _doc(text, title=""):
    return {"text": text, "title": title, "url": "https://example.test/a", "document_id": 1}


def test_artis_is_distinct_from_zbrojovka():
    forms = entity_forms(["Artis Brno"])
    assert "artis brno" in forms
    assert "zbrojovka brno" not in forms


def test_evidence_capped_per_document():
    text = " ".join(f"Teplice injury report number {i} confirmed today." for i in range(200))
    result = EvidenceExtractor().extract_evidence(_doc(text), "ABSENCES_HOME", entities=["Teplice"], max_items=10)
    assert len(result) == 10


def test_profile_domain_uses_topic_terms_not_every_sentence():
    text = "Teplice lead the table this season. The stadium café sells coffee and cakes daily."
    result = EvidenceExtractor().extract_evidence(_doc(text), "TEAM_PROFILE_HOME", entities=["Teplice"])
    assert len(result) == 1 and "table" in result[0].text_fragment
