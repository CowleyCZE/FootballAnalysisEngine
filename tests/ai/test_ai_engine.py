import json
import sqlite3
import pytest
from unittest.mock import MagicMock

from app.ai.schemas import AnalysisResult
from app.ai.validator import AIValidator
from app.ai.context_builder import ContextBuilder
from app.ai.synthesizer import AISynthesizer

def test_json_validator_valid():
    sample_json = '''
    {
      "match_id": 10,
      "status": "complete",
      "data_quality": {
        "score": 0.9,
        "source_count": 5,
        "independent_sources": 3,
        "official_sources": 1,
        "conflicts": 0,
        "freshness_score": 1.0,
        "missing_data": []
      },
      "key_factors": [
        {"factor": "Klíčový hráč zraněn", "importance": 0.8, "evidence_ids": [101]}
      ],
      "uncertainties": [],
      "conflicts_noted": [],
      "conclusion": "Tým A má oslabenou sestavu."
    }
    '''
    valid, obj, err, raw_dict = AIValidator.validate(sample_json, AnalysisResult)
    assert valid is True
    assert obj.match_id == 10
    assert obj.conclusion == "Tým A má oslabenou sestavu."

def test_hallucination_and_missing_data():
    builder = ContextBuilder()
    match_info = {"match_id": 1, "home": "Arsenal", "away": "Chelsea"}
    # Prázdné claims/statistiky jsou explicitně prázdný vstup; ContextBuilder
    # nesmí kvůli nim číst produkční DB.
    context = builder.build_context(match_info, claims=[], statistics={})
    assert "claims" in context["data_quality"]["missing_data"]
    assert "statistics" in context["data_quality"]["missing_data"]
    assert context["data_quality"]["score"] < 0.5

def test_conflicts_preservation():
    builder = ContextBuilder()
    match_info = {"match_id": 2, "home": "Sparta", "away": "Slavia"}
    claims = [
        {
            "id": 1,
            "subject": "Hráč X",
            "predicate": "status",
            "object": "injured",
            "confidence": 0.9,
            "evidence": [{"id": 1, "source": "BBC", "url": "https://bbc.com", "text_fragment": "Hráč X je zraněn"}]
        }
    ]
    conflicts = [{"type": "PLAYER_AVAILABILITY", "description": "Zdroj A tvrdí zraněn, Zdroj B tvrdí trénuje"}]
    context = builder.build_context(match_info, claims, statistics={"xg_home": 1.5}, conflicts=conflicts)
    assert len(context["conflicts"]) == 1
    assert context["data_quality"]["conflicts"] == 1

def test_synthesizer_reproducibility_and_db(tmp_path):
    db_file = str(tmp_path / "test_ai.db")
    
    mock_client = MagicMock()
    mock_client.model = "qwen2.5:7b"
    mock_client.generate.return_value = '''
    {
      "match_id": 50,
      "status": "complete",
      "data_quality": {
        "score": 0.85,
        "source_count": 2,
        "independent_sources": 1,
        "official_sources": 1,
        "conflicts": 0,
        "freshness_score": 0.9,
        "missing_data": []
      },
      "key_factors": [],
      "uncertainties": [],
      "conflicts_noted": [],
      "conclusion": "Vyrovnaný zápas."
    }
    '''

    synthesizer = AISynthesizer(client=mock_client, db_path=db_file)
    
    match_info = {"match_id": 50, "home": "Arsenal", "away": "Chelsea"}
    claims = []
    stats = {"ppg_home": 2.1}

    res1, run_id1 = synthesizer.analyze_match(match_info, claims, stats)
    res2, run_id2 = synthesizer.analyze_match(match_info, claims, stats)

    assert res1 is not None
    assert res1.match_id == 50

    # Zkontrolovat záznamy v DB
    conn = sqlite3.connect(db_file)
    rows = conn.execute("SELECT run_id, input_hash, output_hash, status FROM ai_runs").fetchall()
    conn.close()

    assert len(rows) == 2
    # Stejná data -> stejný input_hash
    assert rows[0][1] == rows[1][1]
    assert rows[0][3] == "SUCCESS"


def test_context_builder_does_not_implicitly_load_database(tmp_path):
    db_file = str(tmp_path / "context.db")
    builder = ContextBuilder(db_path=db_file)
    context = builder.build_context(
        {"match_id": 1, "home": "Arsenal", "away": "Chelsea"},
        claims=[],
        statistics={},
    )
    assert context["claims"] == []
    assert context["statistics"] == {}
    assert context["data_quality"]["missing_data"] == ["claims", "statistics"]


def test_context_builder_counts_independent_publishers_and_real_freshness():
    builder = ContextBuilder()
    context = builder.build_context(
        {"match_id": 1, "home": "Arsenal", "away": "Chelsea"},
        claims=[
            {
                "id": 1,
                "subject": "Saka",
                "predicate": "status",
                "object": "injured",
                "confidence": 0.9,
                "evidence": [
                    {
                        "id": 10,
                        "url": "https://arsenal.com/news/1",
                        "published_at": "2026-10-05T10:00:00Z",
                        "source_type": "official_club",
                    },
                    {
                        "id": 11,
                        "url": "https://www.bbc.com/sport/football/1",
                        "published_at": "2026-10-04T10:00:00Z",
                        "source_type": "major_news",
                    },
                ],
            }
        ],
        statistics={"xg_home": 1.2},
    )
    assert context["data_quality"]["source_count"] == 2
    assert context["data_quality"]["independent_sources"] == 2
    assert context["data_quality"]["official_sources"] == 1
    assert 0.0 < context["data_quality"]["freshness_score"] <= 1.0
