"""Běh M976_9ae1: šum v RIVALRY claimech (hooligans.cz reels, lišta tipů/aplikace, „sedmá liga“)."""
import pytest

from app.research.relevance_filter import is_boilerplate_sentence, sentence_is_relevant


@pytest.mark.parametrize("sentence", [
    "Gerelateerde reelsHooligans.cz18 d.Hooligans.cz75 d.Hooligans.cz117 d.",
    "Outsider & Dark Horse Tips Download our app News & Predictions",
    "Kašík baví sedmou ligu parádními trefami z dálky TémaPříběhy osobností ZlínskaKraje14.",
    "Sparta vyhrála okresní přebor v roce 1998.",
])
def test_run_9ae1_noise_is_boilerplate(sentence):
    assert is_boilerplate_sentence(sentence)
    assert not sentence_is_relevant(sentence)


@pytest.mark.parametrize("sentence", [
    "Sobotní krajské derby rozhodl v 10. minutě Zlín a porazil Slovácko 1:0.",
    "Zlín v závěrečném kole skupiny o udržení Chance Ligy porazil Slovácko 1:0.",
])
def test_regional_derby_sentences_are_kept(sentence):
    assert sentence_is_relevant(sentence)
