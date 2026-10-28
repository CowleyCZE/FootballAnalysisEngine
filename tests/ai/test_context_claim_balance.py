"""AI kontext: vyvážený výběr claimů (M590) a pojistka na .env hodnoty Ollamy."""
from pathlib import Path

import pytest

from app.ai.context_builder import ContextBuilder


def _claim(i, predicate, confidence):
    return {"claim_id": i, "subject": f"s{i}", "predicate": predicate, "object": f"o{i}",
            "confidence": confidence, "status": "VALID", "evidence": []}


def _builder():
    return ContextBuilder(db_path="")


def test_noisy_predicate_does_not_fill_whole_context():
    claims = [_claim(i, "noise", 1.0) for i in range(30)]
    claims += [_claim(100 + i, "availability_status", 0.8) for i in range(3)]
    claims += [_claim(200 + i, "team_form", 0.7) for i in range(3)]

    selected = _builder()._select_balanced_claims(claims, 10)

    predicates = [c["predicate"] for c in selected]
    assert len(selected) == 10
    assert predicates.count("availability_status") == 3
    assert predicates.count("team_form") == 3
    assert predicates.count("noise") == 4


def test_result_sorted_by_confidence_and_unchanged_when_everything_fits():
    claims = [_claim(1, "a", 0.5), _claim(2, "b", 0.9), _claim(3, "a", 0.7)]
    selected = _builder()._select_balanced_claims(claims, 10)
    assert [c["claim_id"] for c in selected] == [2, 3, 1]


def test_selection_is_sorted_by_confidence_when_truncated():
    claims = [_claim(i, "a" if i % 2 else "b", i / 10) for i in range(1, 9)]
    selected = _builder()._select_balanced_claims(claims, 4)
    confidences = [c["confidence"] for c in selected]
    assert confidences == sorted(confidences, reverse=True)
    assert {c["predicate"] for c in selected} == {"a", "b"}


def test_build_context_respects_max_claims_with_mixed_predicates():
    claims = [_claim(i, "noise", 1.0) for i in range(20)]
    claims += [_claim(100 + i, "expected_lineup", 0.6) for i in range(5)]
    context = _builder().build_context(
        match_info={"match_id": 0, "home_team": "A", "away_team": "B"},
        claims=claims, statistics={"x": 1}, max_claims=8,
    )
    predicates = [c["predicate"] for c in context["claims"]]
    assert len(predicates) == 8
    assert predicates.count("expected_lineup") == 4
    assert predicates.count("noise") == 4


def test_project_env_keeps_safe_ollama_values():
    """Lokální .env přebíjí výchozí hodnoty z kódu (v M590 měl timeout 60 s a 1 pokus)."""
    env_file = Path(__file__).resolve().parents[2] / ".env"
    if not env_file.exists():
        pytest.skip(".env neexistuje")
    values = {}
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip()
    if "OLLAMA_TIMEOUT" in values:
        assert float(values["OLLAMA_TIMEOUT"]) >= 120
    if "OLLAMA_MAX_RETRIES" in values:
        assert int(values["OLLAMA_MAX_RETRIES"]) >= 2
