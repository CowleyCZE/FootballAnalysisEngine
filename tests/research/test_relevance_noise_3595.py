"""Šum z běhu M976_3595 (RIVALRY): lišta tipů a hlavička widgetu zápasu."""
import pytest

from app.research.relevance_filter import is_boilerplate_sentence, sentence_is_relevant


@pytest.mark.parametrize("text", [
    "Premium Horse Racing Tips Premium Football Tips Elite Value Tips",
    "FC Zlín vs Slovácko — Sat, November 7, 2:00 PM UTCFollowmatches1. Liga Round 14Follow1. Liga",
])
def test_navigation_noise_is_boilerplate(text):
    assert is_boilerplate_sentence(text)
    assert not sentence_is_relevant(text)


@pytest.mark.parametrize("text", [
    "Fotbalisté Zlína porazili v derby sousední Slovácko 1:0.",
    "Zlín zakončil sezonu vítězstvím v derby, Slovácko čeká baráž s Artisem",
])
def test_derby_sentences_still_relevant(text):
    assert sentence_is_relevant(text)
