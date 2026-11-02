"""Běh M976_e7ab: předfiltr zmínky týmu u zápasových domén a šablonové nadpisy statistických portálů."""
from types import SimpleNamespace

import pytest

from app.research.engine import ResearchEngine
from app.research.relevance_filter import is_boilerplate_sentence, sentence_is_relevant
from app.research.team_mention import filter_by_team_mention, mentions_any_team, team_forms


def _res(title, content="", url="https://example.com/x"):
    return SimpleNamespace(title=title, content=content, url=url)


def test_team_forms_are_folded_and_include_significant_words():
    assert "slovacko" in team_forms("1. FC Slovácko")
    assert "zlin" in team_forms("Zlín")
    assert "praha" not in team_forms("Slavia Praha")  # víceznačné/obecné slovo samo nestačí


def test_mentions_team_ignores_diacritics_and_case():
    assert mentions_any_team(_res("FC FASTAV ZLIN preview"), ["Zlín", "Slovácko"])
    assert mentions_any_team(_res("x", url="https://zlinsky.denik.cz/fotbal"), ["Zlín"])
    assert not mentions_any_team(_res("Ford Puma E10 Spritverbrauch"), ["Zlín", "Slovácko"])


def test_filter_drops_unrelated_results_for_match_level_domain(monkeypatch):
    monkeypatch.setenv("FAE_REQUIRE_TEAM_MENTION", "1")  # conftest ho v testech vypíná
    results = [_res("Zlín vs Slovácko preview"), _res("Ford Puma forum", url="https://www.ford-puma-forum.de/t")]
    kept = filter_by_team_mention(results, "GENERAL", "Zlín", "Slovácko")
    assert [r.title for r in kept] == ["Zlín vs Slovácko preview"]


@pytest.mark.parametrize("domain", ["REFEREE", "HEAD_TO_HEAD"])
def test_filter_exempts_referee_and_h2h(domain, monkeypatch):
    monkeypatch.setenv("FAE_REQUIRE_TEAM_MENTION", "1")
    results = [_res("Referee statistics overview")]
    assert filter_by_team_mention(results, domain, "Zlín", "Slovácko") == results


def test_filter_can_be_disabled_by_env(monkeypatch):
    monkeypatch.setenv("FAE_REQUIRE_TEAM_MENTION", "0")
    results = [_res("Ford Puma forum")]
    assert filter_by_team_mention(results, "GENERAL", "Zlín", "Slovácko") == results


class _Adapter:
    def __init__(self, results):
        self.results = results
        self.last_diagnostics = None

    def search(self, query, **kwargs):
        return list(self.results)


def _engine(results):
    engine = ResearchEngine.__new__(ResearchEngine)
    engine.search_adapter = _Adapter(results)
    return engine


def _task(domain):
    return SimpleNamespace(domain=domain, home_team="Zlín", away_team="Slovácko", priority=50, data_cutoff_at=None)


def test_engine_search_one_filters_general_domain(monkeypatch):
    monkeypatch.setenv("FAE_REQUIRE_TEAM_MENTION", "1")
    engine = _engine([_res("Zlín – Slovácko sestavy"), _res("Ford Puma forum")])
    res, err, _ = engine._search_one(_task("GENERAL"), {"query": "Zlín Slovácko team news", "type": "discovery"})
    assert err is None
    assert [r.title for r in res] == ["Zlín – Slovácko sestavy"]


def test_engine_search_one_keeps_team_domain_untouched(monkeypatch):
    # *_HOME má týmový subjekt – identitu už hlídá SearchEngine, předfiltr se nepoužije.
    monkeypatch.setenv("FAE_REQUIRE_TEAM_MENTION", "1")
    engine = _engine([_res("Obecný článek bez názvu týmu")])
    res, err, _ = engine._search_one(_task("ABSENCES_HOME"), {"query": "Zlín absences", "type": "discovery"})
    assert err is None
    assert len(res) == 1


@pytest.mark.parametrize("sentence", [
    "Scoring Consistency Home/Away",
    "Goal Trends (Over 2.5)",
    "Defensive Record (Clean Sheet) Home/Away",
    "Recent Form",
    "Liga 2026-2027 Standings & Table",
    "Let's see how statistics change.Zlin vs Slovacko Starting Lineups & FormationsStarting Lineup",
    "Fans have been treated to plenty of action.",
    "FIFA Club World Cup",
])
def test_stats_portal_template_text_is_noise(sentence):
    assert is_boilerplate_sentence(sentence)
    assert not sentence_is_relevant(sentence)


@pytest.mark.parametrize("sentence", [
    "Zlín vyhrál poslední domácí zápas 2:1 nad Karvinou.",
    "On average Zlin scores 0.4 and concedes 1.6 goals in home matches.",
    "Slovácko bude chybět kapitán kvůli žluté kartě.",
])
def test_real_statements_are_not_marked_as_noise(sentence):
    assert not is_boilerplate_sentence(sentence)


@pytest.mark.parametrize("sentence", [
    "play_fill Zlín chystá velký svátek: derby doprovodí obří fanzóna, tisíc piv zdarma",
    "play_fill Posily za milióny a útok na poháry teď nečekejte. Chance Liga9.",
    "Bet Builder Tips Accumulator Tips Today's Super Boosts",
])
def test_teaser_widgets_and_betting_offers_are_noise(sentence):
    assert is_boilerplate_sentence(sentence)
