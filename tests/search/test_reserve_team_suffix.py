from types import SimpleNamespace

from app.search.relevance import calculate_identity_confidence, calculate_relevance, mentions_reserve_team


def _res(title, content=""):
    return SimpleNamespace(title=title, content=content, url="https://www.sofascore.com/x", published_at=None)


def test_reserve_team_suffix_detected():
    assert mentions_reserve_team("1. fc slovácko b vs fc zlín b live score", "Zlín", "Slovácko")
    assert not mentions_reserve_team("fc zlín vs 1. fc slovácko live score, bilance", "Zlín", "Slovácko")
    assert not mentions_reserve_team("zlín bude hrát b. skupinu", "Zlín", "Slovácko")


def test_reserve_match_gets_zero_identity_and_penalty():
    bad = _res("1. FC Slovácko B vs FC Zlín B live score, H2H and lineups | Sofascore")
    good = _res("FC Zlín vs 1. FC Slovácko live score, H2H and lineups | Sofascore")
    assert calculate_identity_confidence(bad, "Zlín", "Slovácko") == 0.0
    assert calculate_identity_confidence(good, "Zlín", "Slovácko") > 0.0
    assert calculate_relevance(bad, home_team="Zlín", away_team="Slovácko") < calculate_relevance(
        good, home_team="Zlín", away_team="Slovácko")
