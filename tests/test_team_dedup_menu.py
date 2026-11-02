"""TODO 11.28: menu zakládalo týmy bez aliasů („Zlín“ vedle „FC FASTAV Zlin“) → zápas bez historie a xG (běh M976)."""
import sqlite3

import menu
from app.database.schema import initialize_database
from app.database.team_identity import consolidate_legacy_team_ids


def _db(tmp_path):
    path = str(tmp_path / "teams.db")
    initialize_database(path)
    return path


def test_menu_reuses_existing_team_via_alias(tmp_path):
    path = _db(tmp_path)
    with sqlite3.connect(path) as conn:
        conn.execute("INSERT INTO teams(id, name, normalized_name) VALUES (16, 'FC FASTAV Zlin', 'zlin')")
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        assert menu.get_or_create_team(cursor, "Zlín") == 16
        assert menu.get_or_create_team(cursor, "FC Zlín") == 16
        assert conn.execute("SELECT COUNT(*) FROM teams").fetchone()[0] == 1


def test_consolidation_merges_existing_duplicate_and_remaps_matches(tmp_path):
    path = _db(tmp_path)
    with sqlite3.connect(path) as conn:
        conn.execute("INSERT INTO teams(id, name, normalized_name) VALUES (16, 'FC FASTAV Zlin', 'zlin')")
        conn.execute("INSERT INTO teams(id, name, normalized_name) VALUES (217, 'Zlín', 'zlín')")
        conn.execute("INSERT INTO teams(id, name, normalized_name) VALUES (5, 'Teplice', 'teplice')")
        conn.execute("INSERT INTO matches(id, competition, home_team_id, away_team_id, scheduled_at, status) "
                     "VALUES (976, 'Chance Liga', 217, 5, '2026-11-07T14:00:00+00:00', 'RESOLVED')")
        conn.commit()
        result = consolidate_legacy_team_ids(conn)
        assert result["merged"] == 1
        zlin = conn.execute("SELECT id FROM teams WHERE normalized_name='zlin'").fetchall()
        assert len(zlin) == 1
        home = conn.execute("SELECT home_team_id FROM matches WHERE id=976").fetchone()[0]
        assert home == zlin[0][0]
        # opakované volání už nic nesloučí
        assert consolidate_legacy_team_ids(conn)["merged"] == 0
