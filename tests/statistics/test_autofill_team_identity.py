"""Autofill historie musí napojit zápasy na týmy cílového zápasu i při duplicitách týmů v DB."""
import sqlite3

from app.database.schema import initialize_database
from app.statistics.history_autofill import HistoryAutoFiller, resolve_team_key


def _setup(tmp_path):
    db = str(tmp_path / "t.db")
    initialize_database(db)
    with sqlite3.connect(db) as conn:
        # Duplicity z dřívějších importů (nižší id) + týmy cílového zápasu (vyšší id).
        conn.execute("INSERT INTO teams(id, name, normalized_name) VALUES (1, 'FK Teplice', 'fk teplice')")
        conn.execute("INSERT INTO teams(id, name, normalized_name) VALUES (2, 'FC Zbrojovka Brno', 'fc zbrojovka brno')")
        conn.execute("INSERT INTO teams(id, name, normalized_name) VALUES (10, 'Teplice', 'teplice')")
        conn.execute("INSERT INTO teams(id, name, normalized_name) VALUES (11, 'Artis Brno', 'artis brno')")
    return db


DATA = {
    "name": "Czech 2020-21",
    "matches": [
        {"date": "2020-09-12", "team1": "FK Teplice", "team2": "FC Zbrojovka Brno", "score": {"ft": [2, 1]}},
        {"date": "2020-09-19", "team1": "FC Zbrojovka Brno", "team2": "FK Teplice", "score": {"ft": [0, 0]}},
    ],
}
CUTOFF = "2026-10-22T03:38:48"


def test_history_uses_target_match_team_ids(tmp_path):
    db = _setup(tmp_path)
    filler = HistoryAutoFiller(db_path=db, cache_dir=tmp_path / "cache")
    preferred = {resolve_team_key("Teplice"): 10, resolve_team_key("Artis Brno"): 11}
    assert filler._import_rows(DATA, "Chance Liga", CUTOFF, preferred) == 2
    assert filler._team_history_count(10, 11, CUTOFF) == 2
    with sqlite3.connect(db) as conn:
        ids = {tuple(r) for r in conn.execute("SELECT home_team_id, away_team_id FROM matches")}
    assert ids == {(10, 11), (11, 10)}


def test_history_count_matches_either_team_in_either_role(tmp_path):
    db = _setup(tmp_path)
    filler = HistoryAutoFiller(db_path=db, cache_dir=tmp_path / "cache")
    preferred = {resolve_team_key("Teplice"): 10, resolve_team_key("Artis Brno"): 11}
    filler._import_rows(DATA, "Chance Liga", CUTOFF, preferred)
    assert filler._team_history_count(11, 10, CUTOFF) == 2
    assert filler._team_history_count(10, 999, CUTOFF) == 2


def test_without_preferred_falls_back_to_first_exact_key(tmp_path):
    db = _setup(tmp_path)
    filler = HistoryAutoFiller(db_path=db, cache_dir=tmp_path / "cache")
    filler._import_rows(DATA, "Chance Liga", CUTOFF)
    with sqlite3.connect(db) as conn:
        ids = {tuple(r) for r in conn.execute("SELECT home_team_id, away_team_id FROM matches")}
    assert ids == {(1, 2), (2, 1)}
