"""TODO 2.6 – slučování týmů: přesná normalizovaná shoda + tabulka aliasů, žádná substring shoda."""
import sqlite3

import pytest

from app.database.schema import initialize_database
from app.statistics import history_autofill as ha
from app.statistics.history_autofill import HistoryAutoFiller, canonical_team_key, resolve_team_key


@pytest.fixture
def conn(tmp_path):
    path = str(tmp_path / "teams.db")
    initialize_database(path)
    c = sqlite3.connect(path)
    c.execute("INSERT INTO teams(id, name, normalized_name) VALUES (1, 'Sparta Praha', 'sparta praha'), (2, 'FC Zlín', 'fc zlin')")
    c.commit()
    yield c
    c.close()


def test_canonical_key_strips_prefixes_but_keeps_distinguishing_suffix():
    assert canonical_team_key("AC Sparta Praha") == canonical_team_key("Sparta Praha")
    assert canonical_team_key("1. FC Slovácko") == canonical_team_key("Slovácko") == "slovacko"
    assert canonical_team_key("Baník Ostrava") == canonical_team_key("FC Banik Ostrava")
    assert canonical_team_key("Sparta Praha B") != canonical_team_key("Sparta Praha")


def test_b_team_is_not_merged_with_first_team(conn):
    new_id = HistoryAutoFiller._team_id(conn, "Sparta Praha B", "Liga")
    assert new_id not in (1, 2)
    assert HistoryAutoFiller._team_id(conn, "Sparta Praha B", "Liga") == new_id  # podruhé se najde
    assert HistoryAutoFiller._team_id(conn, "AC Sparta Praha", "Liga") == 1


def test_no_substring_matching(conn):
    dukla = HistoryAutoFiller._team_id(conn, "Dukla", "Liga")
    dukla_praha = HistoryAutoFiller._team_id(conn, "Dukla Praha", "Liga")
    assert dukla != dukla_praha


def test_alias_table_merges_known_variants(conn):
    # config/team_aliases.yaml: "Fastav Zlín" je alias hlavního názvu "Zlín"
    assert resolve_team_key("Fastav Zlín") == resolve_team_key("FC Zlín")
    assert HistoryAutoFiller._team_id(conn, "FC Fastav Zlín", "Liga") == 2


def test_custom_alias_file(conn, tmp_path, monkeypatch):
    alias_file = tmp_path / "aliases.yaml"
    alias_file.write_text('aliases:\n  "Sparta Praha":\n    - "Letná"\n', encoding="utf-8")
    monkeypatch.setattr(ha, "ALIASES_FILE", alias_file)
    ha._load_aliases.cache_clear()
    try:
        assert HistoryAutoFiller._team_id(conn, "Letná", "Liga") == 1
    finally:
        ha._load_aliases.cache_clear()
