"""TODO 6.3 – schéma se načítá absolutní cestou, test nezávisí na pracovním adresáři."""
import sqlite3
from pathlib import Path

SCHEMA_PATH = Path(__file__).resolve().parents[2] / "database" / "schema.sql"


def test_schema_loads_from_other_working_directory(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    assert SCHEMA_PATH.is_absolute() and SCHEMA_PATH.exists()
    conn = sqlite3.connect(":memory:")
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    conn.close()
    assert {"teams", "matches", "match_predictions"} <= tables
