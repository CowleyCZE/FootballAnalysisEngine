"""TODO 11.27 (běh M976): šum v claimech RIVALRY – YouTube metadata, navigace webu, sázkové návody."""
import pytest

from app.research.relevance_filter import sentence_is_relevant

NOISE = [
    "Kovanda: Rus vydrží mnohem víc než Evropan.Ministr & Mileniál34K 1 dag geleden2:29Rivalita",
    "(Zal hij ooit weer lopen??)Diesel Creek280K 10 uur geledenAutomatisch nagesynchroniseerd19",
    "9 dgn geledenAutomatisch nagesynchroniseerd9:51TIKI-TAKA: Rivalita na hřišti mezi fotbalis",
    "Rivalita mezi Zlínem a Slováckem3.957 weergaven3,9K weergaven6 nov 2015",
    "Přeskočit na obsahMenu Obchodní podmínky Ochrana soukromí",
    "Antigua & Barbuda Jupiler Pro League Bosnia and Herzegovina",
    "Red cards count as one card (not two) in most bookmaker markets.",
    "VIP Predictions — which add player-specific first booking tips, team booking lines",
    "Cards Quick Guide",
]

REAL = [
    "„Derby je derby, je to fotbalový svátek, věřím, že bude plno a že uspějeme,“ má jasno trenér.",
    "Oba celky mají za sebou 15 derby zápasů, bilance vyznívá pro sobotní hosty ze Zlína.",
    "Nejčastějším výsledkem je lahůdkové skóre 3:1.",
]


@pytest.mark.parametrize("sentence", NOISE)
def test_noise_sentences_are_not_relevant(sentence):
    assert not sentence_is_relevant(sentence)


@pytest.mark.parametrize("sentence", REAL)
def test_real_football_sentences_stay_relevant(sentence):
    assert sentence_is_relevant(sentence)
