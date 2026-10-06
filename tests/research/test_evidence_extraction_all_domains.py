from datetime import datetime, timezone
from app.research.evidence_extractor import EvidenceExtractor
from app.research.claim_builder import ClaimBuilder


def test_evidence_extractor_and_claim_builder_all_domains():
    extractor = EvidenceExtractor()
    builder = ClaimBuilder()
    now = datetime.now(timezone.utc)

    domains = [
        ("ABSENCES_HOME", "John Doe is injured and ruled out for the match."),
        ("MATCH_IDENTITY", "Sparta vs Slavia kickoff at Letna stadium."),
        ("FORM_HOME", "Sparta won 4 of their last 5 matches in strong form."),
        ("STATISTICS", "Sparta average 2.1 xG and 60% possession per match."),
        ("HEAD_TO_HEAD", "In recent H2H meetings, Slavia won 3 and Sparta won 2."),
        ("EXPECTED_LINEUPS", "Expected starting XI formation is 4-3-3 with Lukas Haraslin."),
        ("WEATHER", "Matchday weather forecast predicts 18 degrees celsius and light rain."),
    ]

    for domain, text in domains:
        doc = {
            "text": text,
            "url": "https://example.org/news",
            "published_at": now,
            "document_id": 42
        }
        ev_list = extractor.extract_evidence(doc, domain)
        assert len(ev_list) >= 1, f"No evidence extracted for domain {domain}"
        assert ev_list[0].document_id == 42
        assert ev_list[0].domain == domain

        claims = builder.build_claims_from_evidence(ev_list, "Sparta")
        assert len(claims) >= 1, f"No claims built for domain {domain}"
        assert claims[0].evidence_list[0].source_url == "https://example.org/news"
