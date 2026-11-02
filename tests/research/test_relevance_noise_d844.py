"""Šum z běhu M976_d844 (RIVALRY): český seznam zemí a widget „Free.Follow“."""
import pytest

from app.research.relevance_filter import sentence_is_relevant


@pytest.mark.parametrize("text", [
    "Bosna a Hercegovina Chance Národní Liga Dominikánská republika",
    "Free.Follow ZlínFollow SlováckoZlín host Slovácko at Stadion Letná — Chance Liga.",
])
def test_noise_is_dropped(text):
    assert not sentence_is_relevant(text)


@pytest.mark.parametrize("text", [
    "Na druhé straně je zlínským rekordmanem Bohumil Páník, který vedl mužstvo v šesti derby.",
    "Fotbalisté Zlína porazili v derby sousední Slovácko 1:0.",
])
def test_derby_sentences_stay(text):
    assert sentence_is_relevant(text)
