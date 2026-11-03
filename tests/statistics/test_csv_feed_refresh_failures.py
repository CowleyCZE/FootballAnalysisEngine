"""TODO 11.33 – selhání aktualizace soutěžních CSV: síťová chyba, timeout, nevalidní CSV.

Downloader nikdy nesmí přepsat existující data; chyba se zapíše s konkrétní diagnostikou
(návratový kód, stderr/stdout) a traceback jde do logu.
"""
import logging
import sqlite3
from datetime import timedelta

import pytest

from app.statistics import csv_data_sync as sync

VALID_CSV = (
    "date,home_team,away_team,home_goals,away_goals,competition\n"
    "2026-09-12,Sparta Praha,Slavia Praha,2,1,Chance Liga\n"
)
FEED = {
    "chance_liga": {"competition": "Chance Liga", "ttl": timedelta(hours=24), "timeout": 5,
                    "script": "fake_downloader.py", "outputs": ["chance_liga_dataset.csv"]},
}


@pytest.fixture
def feed_env(tmp_path, monkeypatch):
    monkeypatch.setattr(sync, "FEEDS", FEED)
    script = tmp_path / "fake_downloader.py"
    script.write_text("", encoding="utf-8")
    monkeypatch.setattr(sync, "_find_feed_script", lambda name: script)
    return tmp_path / "feed.db", script


def _status(db):
    with sqlite3.connect(db) as conn:
        return conn.execute("SELECT status,error FROM competition_data_status WHERE dataset_key='chance_liga'").fetchone()


def _count(db, table):
    with sqlite3.connect(db) as conn:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def test_network_error_in_real_downloader_reports_returncode_and_stderr(tmp_path, monkeypatch):
    script = tmp_path / "boom.py"
    script.write_text("raise ConnectionError('síť nedostupná XYZ')\n", encoding="utf-8")
    rc, out, err = sync._run_downloader(script, tmp_path, 30)
    assert rc != 0
    assert "síť nedostupná XYZ" in err


def test_nonzero_exit_is_error_with_diagnostics_and_keeps_data(feed_env, monkeypatch, caplog):
    db, _ = feed_env
    monkeypatch.setattr(sync, "_run_downloader", lambda s, o, t: (1, "", "Traceback ... ConnectionError: boom"))
    with caplog.at_level(logging.WARNING, logger=sync.LOG.name):
        result = sync.refresh_stale(db, force=True)
    item = result["refreshed"][0]
    assert item["status"] == "ERROR"
    assert "návratovým kódem 1" in item["error"] and "ConnectionError: boom" in item["error"]
    status, error = _status(db)
    assert status == "ERROR" and "ConnectionError: boom" in error
    assert _count(db, "matches") == 0
    # traceback je v logu, nejen obecné varování
    assert any(r.exc_info for r in caplog.records)


def test_timeout_without_csv_is_error(feed_env, monkeypatch):
    db, _ = feed_env

    def timeout(script, outdir, t):
        raise sync.FeedTimeout(t, "partial out", "partial err")

    monkeypatch.setattr(sync, "_run_downloader", timeout)
    item = sync.refresh_stale(db, force=True)["refreshed"][0]
    assert item["status"] == "ERROR"
    assert "časový limit" in item["error"] and "partial err" in item["error"]


@pytest.mark.parametrize("bad_csv", [
    "",                                              # prázdný soubor
    "foo,bar\n1,2\n",                                # chybějící povinné sloupce
    "date,home_team,away_team\n",                    # jen hlavička
    "date,home_team,away_team\nnot-a-date,,\n",      # žádný použitelný řádek
])
def test_invalid_csv_is_rejected_and_existing_data_untouched(feed_env, monkeypatch, bad_csv):
    db, _ = feed_env
    # Předem uložená data ze starého importu.
    old = db.parent / "chance_liga_dataset.csv"
    old.write_text(VALID_CSV, encoding="utf-8")
    sync.import_csv_files([old], db)
    before = _count(db, "matches")
    assert before == 1

    def fake(script, outdir, t):
        (outdir / "chance_liga_dataset.csv").write_text(bad_csv, encoding="utf-8")
        return 0, "stažení hotovo", ""

    monkeypatch.setattr(sync, "_run_downloader", fake)
    item = sync.refresh_stale(db, force=True)["refreshed"][0]
    assert item["status"] == "ERROR"
    assert "nevalidní" in item["error"]
    assert _count(db, "matches") == before
    assert _status(db)[0] == "ERROR"
    assert old.read_text(encoding="utf-8") == VALID_CSV  # zdrojový soubor nepřepsán


def test_valid_csv_is_imported_ok(feed_env, monkeypatch):
    db, _ = feed_env

    def fake(script, outdir, t):
        (outdir / "chance_liga_dataset.csv").write_text(VALID_CSV, encoding="utf-8")
        return 0, "", ""

    monkeypatch.setattr(sync, "_run_downloader", fake)
    item = sync.refresh_stale(db, force=True)["refreshed"][0]
    assert item["status"] == "OK" and item["matches"] == 1
    assert _status(db) == ("OK", None)


def test_validate_feed_csv_counts_usable_rows(tmp_path):
    f = tmp_path / "x.csv"
    f.write_text(VALID_CSV + "2026-09-13,,Slavia Praha,1,1,Chance Liga\n", encoding="utf-8")
    assert sync.validate_feed_csv(f) == 1
    with pytest.raises(ValueError, match="chybí nebo je prázdný"):
        sync.validate_feed_csv(tmp_path / "missing.csv")
