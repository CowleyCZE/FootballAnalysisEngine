from app.research.evidence_extractor import EvidenceExtractor


def _doc(title, text, url="https://example.com/injuries"):
    return {"title": title, "text": text, "url": url, "document_id": 1}


def test_absences_generic_page_keeps_only_sentences_about_the_team():
    text = (
        "Brighton midfielder is injured with a hamstring problem for weeks.\n"
        "Jablonec defender is sidelined with a knee injury after the last match.\n"
        "Wolverhampton striker is suspended for three matches."
    )
    ev = EvidenceExtractor().extract_evidence(_doc("Premier League injury table", text), "ABSENCES_HOME", entities=["Jablonec"])
    assert [e.text_fragment for e in ev] == ["Jablonec defender is sidelined with a knee injury after the last match."]


def test_absences_page_without_team_sentences_gives_no_fallback_evidence():
    text = "Brighton midfielder is injured with a hamstring problem.\nJablonec is mentioned only in the footer of the page."
    ev = EvidenceExtractor().extract_evidence(_doc("Premier League injuries", text), "ABSENCES_HOME", entities=["Jablonec"])
    assert all("Brighton" not in e.text_fragment for e in ev)


def test_absences_team_page_keeps_all_matching_sentences():
    text = "Defender Novak is injured and will miss the derby.\nStriker Svoboda is doubtful with a knock."
    ev = EvidenceExtractor().extract_evidence(_doc("Jablonec injury news", text), "ABSENCES_HOME", entities=["Jablonec"])
    assert len(ev) == 2
