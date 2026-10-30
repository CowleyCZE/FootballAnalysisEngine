"""TODO 11.26 – import CSV, jednotná identita týmů a audit povolených týmů."""
import sqlite3
import sys

import pytest

from app.statistics.csv_data_sync import import_csv_files

MATCH_CSV = (
    "date,home_team,away_team,home_goals,away_goals,competition\n"
    "2026-09-12,Sparta Praha,Slavia Praha,2,1,Chance Liga\n"
    "2026-09-20,Slavia Praha,AC Sparta Praha,0,0,Chance Liga\n"
)
XG_ONLY_CSV = (
    "date,home_team,away_team,home_xg,away_xg,competition\n"
    "2026-09-12,Sparta Praha,Slavia Praha,1.7,0.8,Chance Liga\n"
)


def _count(db, sql):
    with sqlite3.connect(db) as conn:
        return conn.execute(sql).fetchone()[0]


def test_import_is_idempotent_and_merges_team_aliases(tmp_path):
    db = tmp_path / "sync.db"
    csv_file = tmp_path / "chance_liga_dataset.csv"
    csv_file.write_text(MATCH_CSV, encoding="utf-8")

    first = import_csv_files([csv_file], db)
    assert first["errors"] == []
    assert first["matches"] == 2

    snapshot = (
        _count(db, "SELECT COUNT(*) FROM teams"),
        _count(db, "SELECT COUNT(*) FROM matches"),
        _count(db, "SELECT COUNT(*) FROM match_statistics"),
    )
    # „AC Sparta Praha“ a „Sparta Praha“ jsou jedna identita.
    assert snapshot == (2, 2, 2)

    import_csv_files([csv_file], db)
    assert (
        _count(db, "SELECT COUNT(*) FROM teams"),
        _count(db, "SELECT COUNT(*) FROM matches"),
        _count(db, "SELECT COUNT(*) FROM match_statistics"),
    ) == snapshot
    assert _count(db, "SELECT COUNT(*) FROM matches WHERE status='RESOLVED'") == 2


def test_sparse_xg_file_does_not_create_matches(tmp_path):
    db = tmp_path / "xg.db"
    csv_file = tmp_path / "czech_league_xg_dataset.csv"
    csv_file.write_text(XG_ONLY_CSV, encoding="utf-8")

    result = import_csv_files([csv_file], db)

    assert result["errors"] == []
    assert result["xg_rows"] == 1
    assert result["matches"] == 0
    assert _count(db, "SELECT COUNT(*) FROM matches") == 0
    assert _count(db, "SELECT COUNT(*) FROM match_xg_observations") == 1


def _run_audit(monkeypatch, capsys, db, data_dir):
    from scripts import audit_team_allowlist as audit

    # Kořenové exporty projektu se do testu nesmí míchat.
    monkeypatch.setattr(audit, "ROOT", data_dir.parent)
    monkeypatch.setattr(sys, "argv", ["audit", "--db", str(db), "--data-dir", str(data_dir)])
    code = audit.main()
    return code, capsys.readouterr().out


def test_audit_passes_when_db_matches_csv_and_flags_foreign_team(tmp_path, monkeypatch, capsys):
    data_dir = tmp_path / "data_csv"
    data_dir.mkdir()
    csv_file = data_dir / "chance_liga_dataset.csv"
    csv_file.write_text(MATCH_CSV, encoding="utf-8")
    db = tmp_path / "audit.db"
    import_csv_files([csv_file], db)

    code, out = _run_audit(monkeypatch, capsys, db, data_dir)
    assert code == 0, out
    assert "Týmy mimo povolené zdroje: 0" in out

    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO teams(name, normalized_name) VALUES ('Cizi Klub Nikde', 'cizi klub nikde')")
    code, out = _run_audit(monkeypatch, capsys, db, data_dir)
    assert code == 1
    assert "MIMO DB" in out and "Cizi Klub Nikde" in out


def test_audit_reports_csv_team_missing_in_db(tmp_path, monkeypatch, capsys):
    data_dir = tmp_path / "data_csv"
    data_dir.mkdir()
    (data_dir / "chance_liga_dataset.csv").write_text(MATCH_CSV, encoding="utf-8")
    db = tmp_path / "empty.db"
    from app.database.schema import initialize_database

    initialize_database(str(db))

    code, out = _run_audit(monkeypatch, capsys, db, data_dir)
    assert code == 1
    assert "CHYBÍ DB" in out
