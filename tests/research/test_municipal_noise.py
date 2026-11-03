"""TODO 12.1 – komunální politika, magistrát, dopravní uzavírky a městské zakázky nejsou důkaz o klubu."""
import pytest

from app.research.relevance_filter import is_municipal_noise, sentence_is_relevant


@pytest.mark.parametrize("text", [
    "Budoucí brněnský primátor Hruška chce zlepšit komunikaci s občany.",
    "Magistrát města Brna vypsal veřejnou zakázku na opravu chodníků.",
    "Kvůli dopravní uzavírce na ulici Táborská bude omezena MHD.",
    "Zastupitelstvo městské části schválilo rozpočet města na příští rok.",
])
def test_municipal_sentences_are_noise(text):
    assert is_municipal_noise(text)
    assert not sentence_is_relevant(text)


@pytest.mark.parametrize("text", [
    "Starosta přišel na zápas Artisu Brno s Bohemians a sledoval utkání z tribuny.",
    "Radnice schválila dotaci pro klub, který hraje Chance Ligu.",
    "Artis Brno v sobotu přivítá Bohemians 1905.",
])
def test_football_sentences_mentioning_city_hall_are_kept(text):
    assert not is_municipal_noise(text)
