"""Šum z běhu M976_6f8d (RIVALRY): seznam zemí z výběru regionu, reklama premium."""
import pytest

from app.research.relevance_filter import sentence_is_relevant


@pytest.mark.parametrize("text", [
    "Chance Národní Liga Jihoafrická republika Pobřeží slonoviny",
    "Bosna a Hercegovina Chance Národní Liga Dominikánská republika",
    "Premium unblurs every one — from €15/month.Upgrade to PremiumSee our verified win rate →",
])
def test_noise_dropped(text):
    assert not sentence_is_relevant(text)


@pytest.mark.parametrize("text", [
    "Zlín porazil Slovácko 1:0 a zakončil sezonu vítězstvím v derby.",
    "Slovácko vyhrálo ve Zlíně 0:1, což bylo první vítězné derby po čtyřech prohrách.",
    "Zápas Chance Národní ligy mezi Zlínem a Slováckem skončil remízou 1:1.",
])
def test_legit_sentences_stay(text):
    assert sentence_is_relevant(text)
