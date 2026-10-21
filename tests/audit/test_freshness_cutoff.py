"""TODO 4.1 – čerstvost se počítá vůči data_cutoff_at a podle typu dat."""
from datetime import datetime, timezone

from app.audit.freshness import FreshnessChecker, data_type_for_predicate

CUTOFF = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)


def test_age_is_relative_to_cutoff_not_now():
    # 10 hodin před cutoffem = čerstvé, bez ohledu na to, kolik je hodin dnes
    res = FreshnessChecker.calculate_freshness("2026-11-01T02:00:00+00:00", "injury", reference_at=CUTOFF)
    assert res["age_hours"] == 10.0
    assert res["freshness_score"] > 0.8


def test_same_age_differs_by_data_type():
    pub = "2026-10-30T12:00:00+00:00"  # 48 h před cutoffem
    lineup = FreshnessChecker.calculate_freshness(pub, "lineup", reference_at=CUTOFF)
    stats = FreshnessChecker.calculate_freshness(pub, "statistics", reference_at=CUTOFF)
    assert lineup["freshness_score"] < 0.3 < stats["freshness_score"]


def test_evidence_after_cutoff_has_zero_age():
    res = FreshnessChecker.calculate_freshness("2026-11-02T12:00:00+00:00", "general", reference_at=CUTOFF)
    assert res["age_hours"] == 0.0


def test_missing_or_bad_date_is_low_freshness():
    assert FreshnessChecker.calculate_freshness(None, reference_at=CUTOFF)["freshness_score"] == 0.1
    assert FreshnessChecker.calculate_freshness("není datum", reference_at=CUTOFF)["freshness_score"] == 0.1


def test_predicate_mapping():
    assert data_type_for_predicate("expected_lineup") == "lineup"
    assert data_type_for_predicate("availability_status") == "injury"
    assert data_type_for_predicate("team_profile_fact") == "statistics"
    assert data_type_for_predicate("něco_neznámého") == "general"
    assert data_type_for_predicate(None) == "general"
