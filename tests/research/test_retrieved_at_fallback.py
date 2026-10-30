"""TODO 11.20-c – bezdatové důkazy ze statistických/agregátorských zdrojů: horní mez stáří = retrieved_at."""
from datetime import datetime

import pytest

from app.research.claim_validator import ClaimValidator
from app.research.models import Claim, ClaimStatus, Evidence

CUTOFF = datetime(2026, 10, 24, 12, 0)


class _Registry:
    TYPES = {
        "https://agg.com/a": "aggregator",
        "https://stats.com/a": "statistical_provider",
        "https://club.cz/a": "official_club",
        "https://news.cz/a": "major_news",
        "https://unk.com/a": "unknown",
    }

    def get_source_type(self, url):
        return self.TYPES.get(url, "unknown")


def _claim(url, retrieved_at, predicate="expected_lineup", published_at=None):
    ev = Evidence(source_url=url, text_fragment="Sestava Sparty.", published_at=published_at,
                  retrieved_at=retrieved_at)
    return Claim(subject="Sparta Praha", predicate=predicate, object_value="x",
                 normalized_value=f"{predicate}:x", evidence_list=[ev], confidence=1.0)


def _validate(claim):
    [c] = ClaimValidator().validate_claims([claim], CUTOFF, registry=_Registry())
    return c


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    for key in ("FAE_UNDATED_POLICY", "FAE_RETRIEVED_AT_FALLBACK", "FAE_RETRIEVED_MAX_AGE_DAYS"):
        monkeypatch.delenv(key, raising=False)


@pytest.mark.parametrize("url", ["https://agg.com/a", "https://stats.com/a", "https://club.cz/a"])
def test_recent_retrieval_from_registered_source_is_accepted_with_flag(url):
    c = _validate(_claim(url, "2026-10-23T10:00:00"))
    assert c.status == ClaimStatus.VALID
    assert c.date_source == "retrieved_at"
    assert c.confidence == pytest.approx(0.5)


def test_retrieved_after_cutoff_is_rejected():
    assert _validate(_claim("https://agg.com/a", "2026-10-24T12:00:01")).status == ClaimStatus.REJECTED


def test_too_old_retrieval_is_rejected_and_age_is_configurable(monkeypatch):
    old = "2026-10-10T10:00:00"
    assert _validate(_claim("https://agg.com/a", old)).status == ClaimStatus.REJECTED
    monkeypatch.setenv("FAE_RETRIEVED_MAX_AGE_DAYS", "30")
    assert _validate(_claim("https://agg.com/a", old)).status == ClaimStatus.VALID


@pytest.mark.parametrize("url", ["https://news.cz/a", "https://unk.com/a"])
def test_news_and_unknown_sources_stay_rejected(url):
    assert _validate(_claim(url, "2026-10-23T10:00:00")).status == ClaimStatus.REJECTED


def test_missing_retrieved_at_is_rejected():
    assert _validate(_claim("https://agg.com/a", None)).status == ClaimStatus.REJECTED


def test_wikipedia_never_uses_fallback():
    c = _validate(_claim("https://cs.wikipedia.org/wiki/X", "2026-10-23T10:00:00"))
    assert c.status == ClaimStatus.REJECTED


def test_fallback_can_be_disabled(monkeypatch):
    monkeypatch.setenv("FAE_RETRIEVED_AT_FALLBACK", "0")
    assert _validate(_claim("https://agg.com/a", "2026-10-23T10:00:00")).status == ClaimStatus.REJECTED


def test_dated_evidence_is_unchanged_and_has_no_date_source():
    c = _validate(_claim("https://agg.com/a", "2026-10-23T10:00:00", published_at=datetime(2026, 10, 22)))
    assert c.status == ClaimStatus.VALID and c.date_source is None and c.confidence == 1.0


def test_portals_without_dates_are_registered_for_fallback():
    from app.search.source_registry import SearchSourceRegistry

    registry = SearchSourceRegistry()
    for url in ("https://www.footystats.org/x", "https://www.flashscore.com/x", "https://www.livescore.com/x",
                "https://statz.ai/x", "https://playerstats.football/x", "https://fotbalstat.cz/x",
                "https://www.livesport.cz/x", "https://www.fotmob.com/x"):
        assert registry.get_source_type(url) in {"aggregator", "statistical_provider"}, url


def test_static_claim_keeps_old_065_factor():
    c = _validate(_claim("https://agg.com/a", "2026-10-23T10:00:00", predicate="h2h_record"))
    assert c.status == ClaimStatus.VALID and c.confidence == pytest.approx(0.65) and c.date_source is None
