from __future__ import annotations

import sqlite3

from app.database.history_import import audit_history_import, import_history_records
from app.database.schema import initialize_database


def _match(
    external_id: str,
    home: str = "Sparta Praha",
    away: str = "Slavia Praha",
    scheduled_at: str = "2025-08-10T18:00:00+00:00",
    status: str = "FINISHED",
    home_goals: int | None = 2,
    away_goals: int | None = 1,
    home_xg: float | None = 1.8,
    away_xg: float | None = 0.9,
) -> dict:
    return {
        "external_match_id": external_id,
        "competition": "Chance Liga",
        "season": "2025/2026",
        "home_team": home,
        "away_team": away,
        "scheduled_at": scheduled_at,
        "status": status,
        "home_goals": home_goals,
        "away_goals": away_goals,
        "home_xg": home_xg,
        "away_xg": away_xg,
    }


def test_import_creates_normalized_match_and_statistics(tmp_path):
    db_path = tmp_path / "test.db"
    initialize_database(str(db_path))

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        result = import_history_records(
            conn,
            [_match("CL_1001")],
            competition="Chance Liga",
            season="2025/2026",
        )

        assert result == {"imported": 1, "updated": 0, "skipped": 0}
        assert conn.execute("SELECT COUNT(*) FROM matches").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM match_statistics").fetchone()[0] == 1

        match = conn.execute(
            """
            SELECT m.external_match_id, m.status, s.home_goals, s.away_goals, s.home_xg
            FROM matches m
            JOIN match_statistics s ON s.match_id = m.id
            WHERE m.external_match_id = 'CL_1001'
            """
        ).fetchone()
        assert match["external_match_id"] == "CL_1001"
        assert match["status"] == "FINISHED"
        assert match["home_goals"] == 2
        assert match["away_goals"] == 1
        assert match["home_xg"] == 1.8


def test_repeated_import_does_not_duplicate_matches(tmp_path):
    db_path = tmp_path / "test.db"
    initialize_database(str(db_path))

    with sqlite3.connect(db_path) as conn:
        first = import_history_records(conn, [_match("CL_1001")])
        second = import_history_records(conn, [_match("CL_1001", home_xg=2.1)])

        assert first["imported"] == 1
        assert second["imported"] == 0
        assert second["updated"] == 1
        assert conn.execute("SELECT COUNT(*) FROM matches").fetchone()[0] == 1

        xg = conn.execute(
            """
            SELECT s.home_xg
            FROM matches m
            JOIN match_statistics s ON s.match_id = m.id
            WHERE m.external_match_id = 'CL_1001'
            """
        ).fetchone()[0]
        assert xg == 2.1


def test_invalid_record_is_skipped(tmp_path):
    db_path = tmp_path / "test.db"
    initialize_database(str(db_path))

    invalid = _match("CL_1002")
    invalid["home_goals"] = -1

    with sqlite3.connect(db_path) as conn:
        result = import_history_records(conn, [invalid])

        assert result == {"imported": 0, "updated": 0, "skipped": 1}
        assert conn.execute("SELECT COUNT(*) FROM matches").fetchone()[0] == 0


def test_audit_detects_missing_xg_and_result_gaps(tmp_path):
    db_path = tmp_path / "test.db"
    initialize_database(str(db_path))

    records = [
        _match("CL_1001"),
        _match("CL_1002", home_xg=None, away_xg=None),
        _match("CL_1003", status="SCHEDULED", home_goals=None, away_goals=None, home_xg=None, away_xg=None),
    ]

    with sqlite3.connect(db_path) as conn:
        import_history_records(conn, records)
        report = audit_history_import(conn, competition="Chance Liga")

        assert report["total_matches"] == 3
        assert report["duplicate_external_ids"] == 0
        assert report["finished_without_result"] == 0
        assert report["future_finished_matches"] == 0
        assert report["finished_matches_missing_xg"] == 1
