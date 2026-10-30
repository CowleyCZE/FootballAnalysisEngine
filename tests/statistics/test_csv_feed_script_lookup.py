"""Downloadery CSV feedů se hledají v kořeni projektu i v database/data_csv (nález z běhu M943)."""
import pytest

from app.statistics import csv_data_sync as sync


def test_find_feed_script_checks_root_then_data_dir(tmp_path, monkeypatch):
    root, data = tmp_path / "root", tmp_path / "data"
    root.mkdir()
    data.mkdir()
    monkeypatch.setattr(sync, "ROOT", root)
    monkeypatch.setattr(sync, "DEFAULT_DATA_DIR", data)
    (data / "a.py").write_text("", encoding="utf-8")
    assert sync._find_feed_script("a.py") == data / "a.py"
    (root / "a.py").write_text("", encoding="utf-8")
    assert sync._find_feed_script("a.py") == root / "a.py"
    with pytest.raises(FileNotFoundError):
        sync._find_feed_script("missing.py")


def test_all_configured_feed_scripts_exist_in_project():
    for key, feed in sync.FEEDS.items():
        assert sync._find_feed_script(feed["script"]).is_file(), key
