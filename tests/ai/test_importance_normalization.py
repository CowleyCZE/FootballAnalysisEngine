"""Běh M976_9599: model vrátil importance 3 / 2 → Pydantic chyba → zbytečný pád AI větve."""
import pytest
from pydantic import ValidationError

from app.ai.schemas import AIOutput, KeyFactor
from app.research.relevance_filter import sentence_is_relevant


@pytest.mark.parametrize("raw,expected", [(0.7, 0.7), (1, 1.0), (0, 0.0), (3, 0.3), (2, 0.2), (10, 1.0), (80, 0.8)])
def test_importance_is_normalized(raw, expected):
    assert KeyFactor(factor="x", importance=raw).importance == pytest.approx(expected)


@pytest.mark.parametrize("raw", [-1, 101, 1000, "vysoká"])
def test_invalid_importance_still_rejected(raw):
    with pytest.raises(ValidationError):
        KeyFactor(factor="x", importance=raw)


def test_ai_output_with_rank_importance_validates():
    out = AIOutput(conclusion="c", key_factors=[
        {"factor": "a", "importance": 3, "evidence_ids": [1]},
        {"factor": "b", "importance": 2, "evidence_ids": [2]},
    ])
    assert [f.importance for f in out.key_factors] == [pytest.approx(0.3), pytest.approx(0.2)]


@pytest.mark.parametrize("text", [
    "Premium Staking Plan Get TipMan Premium Premium Staking Plan",
    "This match is part of the 1. You can check the recent head-to-head encounters, as well as",
])
def test_new_noise_markers(text):
    assert not sentence_is_relevant(text)
