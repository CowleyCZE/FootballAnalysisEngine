"""TODO 11.20-d – datum z Wikipedie není ověřením aktuálnosti u časově citlivých tvrzení."""
from datetime import datetime

import pytest

from app.research.claim_validator import ClaimValidator, is_encyclopedic_source
from app.research.models import Claim, ClaimStatus, Evidence

CUTOFF = datetime(2026, 10, 24, 12, 0)
WIKI = "https://cs.wikipedia.org/wiki/AC_Sparta_Praha"


def _claim(predicate, url, published_at=datetime(2026, 10, 1)):
    ev = Evidence(source_url=url, text_fragment="Text tvrzení o týmu.", published_at=published_at)
    return Claim(subject="Sparta Praha", predicate=predicate, object_value="x",
                 normalized_value=f"{predicate}:x", evidence_list=[ev], confidence=1.0)


@pytest.mark.parametrize("url,expected", [
    (WIKI, True),
    ("https://en.wikipedia.org/wiki/X", True),
    ("https://www.wikidata.org/wiki/Q1", True),
    ("https://notwikipedia.org/x", False),
    ("https://www.idnes.cz/fotbal", False),
])
def test_is_encyclopedic_source(url, expected):
    assert is_encyclopedic_source(url) is expected


@pytest.mark.parametrize("predicate", ["availability_status", "team_form", "expected_lineup", "motivation_context", "fatigue_context"])
def test_wikipedia_dated_time_sensitive_claim_is_rejected(predicate, monkeypatch):
    monkeypatch.delenv("FAE_UNDATED_POLICY", raising=False)
    [c] = ClaimValidator().validate_claims([_claim(predicate, WIKI)], CUTOFF)
    assert c.status == ClaimStatus.REJECTED


def test_wikipedia_static_claim_keeps_working(monkeypatch):
    monkeypatch.delenv("FAE_UNDATED_POLICY", raising=False)
    [c] = ClaimValidator().validate_claims([_claim("h2h_record", WIKI)], CUTOFF)
    assert c.status == ClaimStatus.VALID


def test_news_site_with_date_is_not_affected(monkeypatch):
    monkeypatch.delenv("FAE_UNDATED_POLICY", raising=False)
    [c] = ClaimValidator().validate_claims([_claim("team_form", "https://www.idnes.cz/a")], CUTOFF)
    assert c.status == ClaimStatus.VALID


def test_allow_policy_restores_wikipedia(monkeypatch):
    monkeypatch.setenv("FAE_UNDATED_POLICY", "allow")
    [c] = ClaimValidator().validate_claims([_claim("team_form", WIKI)], CUTOFF)
    assert c.status == ClaimStatus.VALID
