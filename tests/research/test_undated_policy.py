from datetime import datetime

import pytest

from app.research.claim_validator import ClaimValidator, source_weight
from app.research.models import Claim, ClaimStatus, Evidence

CUTOFF = datetime(2026, 10, 24, 12, 0)


def _claim(predicate, published_at=None, url="https://example.cz/a"):
    ev = Evidence(source_url=url, text_fragment="Text tvrzení o týmu.", published_at=published_at)
    return Claim(subject="Sparta Praha", predicate=predicate, object_value="x",
                 normalized_value=f"{predicate}:x", evidence_list=[ev], confidence=1.0)


@pytest.mark.parametrize("predicate", [
    "availability_status", "absence_report", "team_form", "expected_lineup",
    "motivation_context", "fatigue_context",
])
def test_undated_time_sensitive_claim_is_rejected(predicate, monkeypatch):
    monkeypatch.delenv("FAE_UNDATED_POLICY", raising=False)
    [c] = ClaimValidator().validate_claims([_claim(predicate)], CUTOFF)
    assert c.status == ClaimStatus.REJECTED


@pytest.mark.parametrize("predicate", ["h2h_record", "rivalry_context", "team_profile_fact"])
def test_undated_static_claim_is_kept_with_lower_confidence(predicate, monkeypatch):
    monkeypatch.delenv("FAE_UNDATED_POLICY", raising=False)
    [c] = ClaimValidator().validate_claims([_claim(predicate)], CUTOFF)
    assert c.status == ClaimStatus.VALID
    assert c.confidence == pytest.approx(0.65)


def test_dated_time_sensitive_claim_before_cutoff_is_valid():
    [c] = ClaimValidator().validate_claims([_claim("availability_status", datetime(2026, 10, 23))], CUTOFF)
    assert c.status == ClaimStatus.VALID and c.confidence == 1.0


def test_claim_after_cutoff_is_rejected():
    [c] = ClaimValidator().validate_claims([_claim("availability_status", datetime(2026, 10, 25))], CUTOFF)
    assert c.status == ClaimStatus.REJECTED


def test_allow_policy_restores_old_behaviour(monkeypatch):
    monkeypatch.setenv("FAE_UNDATED_POLICY", "allow")
    [c] = ClaimValidator().validate_claims([_claim("availability_status")], CUTOFF)
    assert c.status == ClaimStatus.VALID


class _FakeRegistry:
    AUTH = {"https://club.cz/a": 1.0, "https://agg.com/a": 0.5, "https://unk.com/a": 0.2}

    def get_authority(self, url):
        return self.AUTH[url]


def test_source_weights_prefer_official_over_aggregator(monkeypatch):
    monkeypatch.delenv("FAE_SOURCE_WEIGHTING", raising=False)
    claims = [_claim("team_form", datetime(2026, 10, 23), url=u) for u in _FakeRegistry.AUTH]
    claims = ClaimValidator().validate_claims(claims, CUTOFF)
    official, aggregator, unknown = ClaimValidator().apply_source_weights(claims, _FakeRegistry())
    assert official.confidence == 1.0
    assert official.confidence > aggregator.confidence > unknown.confidence


def test_best_source_among_evidence_counts(monkeypatch):
    monkeypatch.delenv("FAE_SOURCE_WEIGHTING", raising=False)
    claim = _claim("team_form", datetime(2026, 10, 23), url="https://agg.com/a")
    claim.evidence_list.append(Evidence(source_url="https://club.cz/a", text_fragment="Další text.",
                                        published_at=datetime(2026, 10, 23)))
    [c] = ClaimValidator().apply_source_weights([claim], _FakeRegistry())
    assert c.confidence == 1.0


def test_rejected_claims_are_not_weighted_and_switch_disables(monkeypatch):
    rejected = _claim("team_form")
    rejected.status = ClaimStatus.REJECTED
    [c] = ClaimValidator().apply_source_weights([rejected], _FakeRegistry())
    assert c.confidence == 1.0
    monkeypatch.setenv("FAE_SOURCE_WEIGHTING", "0")
    ok = _claim("team_form", url="https://unk.com/a")
    [c2] = ClaimValidator().apply_source_weights([ok], _FakeRegistry())
    assert c2.confidence == 1.0


def test_source_weight_values():
    assert source_weight(1.0) == 1.0
    assert source_weight(0.5) == 0.75
    assert source_weight(0.2) == 0.6
    assert source_weight(None) == 0.5
