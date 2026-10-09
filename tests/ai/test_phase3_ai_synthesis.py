import sqlite3
import pytest
from datetime import datetime, timezone

from app.ai.context_builder import ContextBuilder
from app.workers.ai_worker import AIWorker
from app.database.schema import initialize_database


@pytest.fixture
def phase3_db(tmp_path):
    db_file = str(tmp_path / "test_phase3.db")
    initialize_database(db_file)

    conn = sqlite3.connect(db_file)
    conn.execute("INSERT INTO teams(id, name, normalized_name) VALUES (1, 'Arsenal', 'arsenal'), (2, 'Chelsea', 'chelsea')")
    conn.execute("INSERT INTO competitions(id, name, country) VALUES (1, 'Premier League', 'England')")
    conn.execute("INSERT INTO matches(id, competition, competition_id, home_team_id, away_team_id, scheduled_at) VALUES (88, 'Premier League', 1, 1, 2, '2026-10-20 20:00:00')")
    
    # Insert run
    conn.execute("INSERT INTO runs(id, run_id, status, started_at) VALUES (1, 'RUN-88', 'RUNNING', '2026-10-20T10:00:00')")

    # Insert claims and evidence
    conn.execute("INSERT INTO claims(id, run_id, match_id, claim_text, claim_type, normalized_claim, status, confidence) VALUES (10, 1, 88, 'Arsenal striker Bukayo Saka is injured', 'injury', 'Saka:UNAVAILABLE', 'VALID', 0.95)")
    conn.execute("INSERT INTO sources(id, domain, name) VALUES (1, 'bbc.com', 'BBC Sport')")
    conn.execute("INSERT INTO documents(id, source_id, url, content_hash, retrieved_at) VALUES (1, 1, 'https://bbc.com/saka', 'hash123', '2026-10-20T09:00:00')")
    conn.execute("INSERT INTO evidence(id, document_id, evidence_type, quoted_text, confidence) VALUES (100, 1, 'TEXT', 'Saka is ruled out for tonight match', 0.95)")
    conn.execute("INSERT INTO claim_evidence(claim_id, evidence_id) VALUES (10, 100)")

    conn.commit()
    conn.close()
    return db_file


def test_context_builder_loads_claims_and_enrich_match_info(phase3_db):
    cb = ContextBuilder(db_path=phase3_db)
    context = cb.build_context(match_info={"match_id": 88, "data_cutoff_at": "2026-10-20 20:00:00"}, run_db_id=1)

    assert context["match"]["home_team"] == "Arsenal"
    assert context["match"]["away_team"] == "Chelsea"
    assert context["match"]["competition"] == "Premier League"
    assert context["match"]["data_cutoff_at"] == "2026-10-20 20:00:00"
    assert len(context["claims"]) == 1
    assert context["claims"][0]["subject"] == "Arsenal"
    assert context["claims"][0]["evidence"][0]["url"] == "https://bbc.com/saka"


def test_ai_worker_returns_insufficient_data_when_no_claims_in_db(phase3_db):
    # Execute AIWorker on match 99 (no claims in DB)
    res = AIWorker.execute({"match_id": 99, "db_path": phase3_db})

    assert res["status"] == "insufficient_data"
    assert res["home_team_analysis"] is None
    assert res["away_team_analysis"] is None
    assert res["data_quality"]["score"] == 0.0
    assert "claims" in res["data_quality"]["missing_data"][0]


def test_ai_worker_executes_with_valid_claims_mock(phase3_db, monkeypatch):
    class MockOllama:
        def __init__(self, *args, **kwargs):
            pass

        def generate(self, prompt, require_json=True):
            assert "STRICT DATA CUTOFF:" in prompt
            assert "Arsenal" in prompt
            return '''
            {
              "match_id": 88,
              "status": "complete",
              "data_quality": {
                "score": 0.9,
                "source_count": 1,
                "independent_sources": 1,
                "official_sources": 0,
                "conflicts": 0,
                "freshness_score": 0.9,
                "missing_data": []
              },
              "home_team_analysis": {
                "strengths": ["Strong attack"],
                "weaknesses": ["Saka absent"],
                "tactical_notes": []
              },
              "key_factors": [
                {
                  "factor": "Saka injury",
                  "importance": 0.8,
                  "evidence_ids": [100]
                }
              ],
              "uncertainties": [],
              "conflicts_noted": [],
              "conclusion": "Arsenal Bez Saka bude mít těžší zápas."
            }
            '''

    monkeypatch.setattr("app.workers.ai_worker.OllamaClient", MockOllama)

    res = AIWorker.execute({"match_id": 88, "run_db_id": 1, "db_path": phase3_db})

    assert res["status"] == "complete"
    assert res["match_id"] == 88
    assert res["key_factors"][0]["factor"] == "Saka injury"
    assert res["home_team_analysis"]["weaknesses"] == ["Saka absent"]
