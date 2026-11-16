from __future__ import annotations

import sqlite3

from app.crawler.chance_liga_history import parse_schedule_html, season_label
from app.database.history_import import audit_history_import, import_history_records
from app.database.schema import initialize_database


HTML = """
<table>
  <tr><th>1.kolo</th></tr>
  <tr>
    <td>pá, 19/07/2024</td>
    <td>AC Sparta Praha</td>
    <td>2:1</td>
    <td>FK Pardubice</td>
  </tr>
  <tr>
    <td>so, 20/07/2024</td>
    <td>FK Jablonec</td>
    <td>-:-</td>
    <td>FK Mladá Boleslav</td>
  </tr>
</table>
"""


def test_history_schedule_imports_into_database(tmp_path):
    db_path = tmp_path / "history.db"
    initialize_database(str(db_path))
    records = parse_schedule_html(HTML, season_label(2024))

    with sqlite3.connect(db_path) as conn:
        result = import_history_records(
            conn,
            records,
            competition="Chance Liga",
        )
        audit = audit_history_import(conn, competition="Chance Liga")

        assert result["imported"] == 2
        assert result["skipped"] == 0
        assert audit["total_matches"] == 2
        assert audit["duplicate_external_ids"] == 0
        assert audit["finished_without_result"] == 0
        assert audit["future_finished_matches"] == 0
        assert audit["finished_matches_missing_xg"] == 1


def test_repeated_history_import_is_idempotent(tmp_path):
    db_path = tmp_path / "history.db"
    initialize_database(str(db_path))
    records = parse_schedule_html(HTML, season_label(2024))

    with sqlite3.connect(db_path) as conn:
        first = import_history_records(conn, records, competition="Chance Liga")
        second = import_history_records(conn, records, competition="Chance Liga")

        assert first["imported"] == 2
        assert second["imported"] == 0
        assert second["updated"] == 2
        assert conn.execute("SELECT COUNT(*) FROM matches").fetchone()[0] == 2
