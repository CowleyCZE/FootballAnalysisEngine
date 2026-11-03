"""TODO 11.35 – absolutní cutoff stáří důkazů: 365 dní časově senzitivní, 10 let statické domény."""
from datetime import datetime, timedelta, timezone

from app.ai.context_builder import ContextBuilder
from app.research.claim_validator import ClaimValidator
from app.research.models import Claim, ClaimStatus, Evidence
from app.research.staleness import STALE_REJECTED, is_stale, max_age_days_for

CUTOFF = datetime(2026, 11, 3, 18, 0, tzinfo=timezone.utc)


def _claim(predicate, age_days):
    ev = Evidence(source_url="https://example.cz/a", text_fragment="x",
                  published_at=CUTOFF - timedelta(days=age_days))
    return Claim(subject="Artis Brno", predicate=predicate, object_value="v", normalized_value="v",
                 evidence_list=[ev])


def test_limits_per_domain():
    assert max_age_days_for("expected_lineup") == 365
    assert max_age_days_for("absence_report") == 365
    assert max_age_days_for("team_form") == 365
    assert max_age_days_for("motivation_context") == 365
    assert max_age_days_for("h2h_record") == 3650
    assert max_age_days_for("rivalry_context") == 3650
    assert max_age_days_for("team_profile_fact") is None


def test_is_stale_uses_cutoff_and_ignores_undated():
    old = CUTOFF - timedelta(days=366)
    assert is_stale(old, CUTOFF, "team_form")
    assert not is_stale(CUTOFF - timedelta(days=364), CUTOFF, "team_form")
    assert not is_stale(None, CUTOFF, "team_form")
    assert not is_stale(CUTOFF - timedelta(days=4000), CUTOFF, "team_profile_fact")
    assert is_stale(CUTOFF - timedelta(days=3651), CUTOFF, "h2h_record")


def test_validator_rejects_16_year_old_evidence_as_stale():
    claims = ClaimValidator().validate_claims(
        [_claim("team_form", 16 * 365), _claim("h2h_record", 16 * 365),
         _claim("team_form", 30), _claim("h2h_record", 5 * 365)], CUTOFF)
    assert [c.status for c in claims] == [ClaimStatus.REJECTED, ClaimStatus.REJECTED,
                                          ClaimStatus.VALID, ClaimStatus.VALID]
    assert claims[0].reject_reason == STALE_REJECTED and claims[1].reject_reason == STALE_REJECTED
    assert claims[2].reject_reason is None


def test_context_builder_applies_domain_limits():
    def c(cid, predicate, age):
        published = (CUTOFF - timedelta(days=age)).isoformat()
        return {"claim_id": cid, "predicate": predicate, "confidence": 0.5,
                "evidence": [{"evidence_id": cid, "published_at": published,
                              "text_fragment": "Slovácko přivítá v sobotu Teplice na domácím stadionu."}]}

    claims = [c(1, "expected_lineup", 400), c(2, "expected_lineup", 100),
              c(3, "h2h_record", 2000), c(4, "h2h_record", 4000), c(5, "team_profile_fact", 700)]
    kept = ContextBuilder._drop_stale_evidence(claims, 730, now=CUTOFF)
    assert [x["claim_id"] for x in kept] == [2, 3, 5]
