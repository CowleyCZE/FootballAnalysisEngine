"""TODO 12.3 – derby/rivalita se přijme jen s oběma soupeři z úkolu; cizí derby = REJECTED_FOREIGN_DERBY."""
from app.research.rivalry_guard import (
    REJECTED_FOREIGN_DERBY, REJECTED_RIVALRY_PAIR, rivalry_rejection_reason,
)

HOME, AWAY = "SK Artis Brno", "Bohemians 1905"


def test_named_foreign_derby_is_rejected():
    text = "Vršovické derby mezi Bohemians a Slavií patří k nejatraktivnějším zápasům ligy."
    assert rivalry_rejection_reason(text, HOME, AWAY) == REJECTED_FOREIGN_DERBY


def test_other_club_instead_of_second_team_is_rejected():
    text = "Bohemians čeká v neděli derby proti Slavia Praha, které přitáhne plný stadion."
    assert rivalry_rejection_reason(text, HOME, AWAY) == REJECTED_FOREIGN_DERBY


def test_derby_with_both_teams_is_accepted():
    text = "Duel Artis Brno proti Bohemians 1905 nemá derby tradici, ale týmy spojuje rivalita z minulosti."
    assert rivalry_rejection_reason(text, HOME, AWAY) is None


def test_generic_derby_without_pair_is_rejected_as_unpaired():
    text = "Derby atmosféra v hledišti je vždy mimořádná."
    assert rivalry_rejection_reason(text, HOME, AWAY) == REJECTED_RIVALRY_PAIR


def test_sentence_without_derby_terms_is_not_judged():
    assert rivalry_rejection_reason("Trenér věří v tři body.", HOME, AWAY) is None
