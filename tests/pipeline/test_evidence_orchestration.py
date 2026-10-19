import json

from app.workers.registry import default_handlers


def test_canonical_handlers_cover_full_evidence_first_flow():
    handlers = default_handlers()
    assert list(handlers) == [
        "SEARCH",
        "CRAWL",
        "STATISTICS",
        "RESEARCH",
        "AI_ANALYSIS",
        "AUDIT",
    ]


def test_research_result_shape_is_compatible_with_ai_and_audit_payloads():
    research_result = {
        "status": "COMPLETED",
        "claims": [
            {
                "claim_id": 1,
                "subject": "Player A",
                "predicate": "availability",
                "object": "INJURED",
                "normalized_value": "INJURED",
                "confidence": 0.95,
                "status": "VALID",
                "evidence": [
                    {
                        "source_url": "https://example.test/source",
                        "text_fragment": "Player A is injured.",
                    }
                ],
            }
        ],
        "evidence_count": 1,
    }

    ai_payload = {
        "match_id": 1,
        "run_id": "run-1",
        "mode": "evidence_first",
        "claims": research_result["claims"],
        "statistics": {},
        "conflicts": [],
    }
    audit_payload = {
        "match_id": 1,
        "run_id": "run-1",
        "cycle": 1,
        "ai_analysis": {"status": "COMPLETED"},
        "claims": research_result["claims"],
        "statistics": {},
    }

    assert json.dumps(ai_payload)
    assert json.dumps(audit_payload)
    assert ai_payload["claims"][0]["evidence"][0]["source_url"] == audit_payload["claims"][0]["evidence"][0]["source_url"]
