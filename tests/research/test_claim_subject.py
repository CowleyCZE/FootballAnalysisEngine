"""TODO 3.3 – subjekt claimů podle domény (HOME/AWAY/zápas)."""
from types import SimpleNamespace

import pytest

from app.research.claim_builder import ClaimBuilder
from app.research.engine import ResearchEngine


def _task(domain):
    return SimpleNamespace(domain=domain, home_team="Sparta Praha", away_team="Slavia Praha")


@pytest.mark.parametrize("domain,expected", [
    ("TEAM_PROFILE_HOME", "Sparta Praha"),
    ("FORM_HOME", "Sparta Praha"),
    ("ABSENCES_AWAY", "Slavia Praha"),
    ("MOTIVATION_AWAY", "Slavia Praha"),
    ("GENERAL", ""),
    ("HEAD_TO_HEAD", ""),
    ("WEATHER", ""),
    ("REFEREE", ""),
    ("RIVALRY", ""),
])
def test_subject_team_name_by_domain(domain, expected):
    assert ResearchEngine.subject_team_name(_task(domain)) == expected


def _evidence(domain, text="Zápas se hraje v dešti."):
    return SimpleNamespace(domain=domain, text_fragment=text, published_at=None,
                           document_id=1, source_url="https://example.org/x")


@pytest.mark.parametrize("domain", ["GENERAL", "HEAD_TO_HEAD", "WEATHER"])
def test_match_level_claims_never_use_away_team_as_subject(domain):
    team = ResearchEngine.subject_team_name(_task(domain))
    claims = ClaimBuilder().build_claims_from_evidence([_evidence(domain)], team)
    assert claims
    assert all("Slavia" not in c.subject and "Sparta" not in c.subject for c in claims)


def test_home_domain_claim_subject_is_home_team():
    team = ResearchEngine.subject_team_name(_task("FORM_HOME"))
    claims = ClaimBuilder().build_claims_from_evidence([_evidence("FORM_HOME")], team)
    assert claims[0].subject == "Sparta Praha"
