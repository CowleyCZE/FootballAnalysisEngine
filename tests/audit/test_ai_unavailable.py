from app.audit.auditor import AdversarialAuditor


def test_audit_marks_insufficient_ai_as_unresolved(tmp_path):
    db_path = str(tmp_path / "audit.db")
    auditor = AdversarialAuditor(db_path=db_path, log_dir=str(tmp_path / "logs"))

    result = auditor.audit(
        match_id=123,
        ai_run_id="ai-test",
        ai_analysis={
            "match_id": 123,
            "status": "insufficient_data",
            "data_quality": {"missing_data": ["Ollama unavailable"]},
            "key_factors": [],
        },
        claims=[],
        statistics={},
        current_cycle=1,
    )

    assert result["status"] == "UNRESOLVED"
    assert result["research_jobs"] == []
    assert any(issue["type"] == "ai_analysis_unavailable" for issue in result["issues"])
