import os
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

# Proměnné prostředí, které ovlivňují chování aplikace (TODO 6.1).
_ISOLATED_PREFIXES = ("FAE_", "OLLAMA_")


@pytest.fixture(autouse=True)
def _isolate_environment(monkeypatch):
    """Testy nesmí záviset na lokálním `.env` ani na prostředí vývojáře.

    Odstraní všechny FAE_* / OLLAMA_* a vypne automatický import historie.
    Test si může potřebné proměnné nastavit vlastním `monkeypatch.setenv`.
    """
    for key in list(os.environ):
        if key.startswith(_ISOLATED_PREFIXES):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("FAE_AUTO_HISTORY", "0")
    yield


@pytest.fixture(scope="session")
def _template_db(tmp_path_factory):
    """Jednou za běh sestaví prázdnou DB se skutečným schématem (TODO 6.2)."""
    from app.database import schema

    path = tmp_path_factory.mktemp("db_template") / "template.db"
    schema._initialize_database(str(path))
    return path


@pytest.fixture(autouse=True)
def _fast_database_init(monkeypatch, _template_db):
    """Inicializace nové (neexistující) DB = kopie hotové šablony místo opakovaného `executescript`.

    Existující soubory (např. testy migrace starého schématu) jdou dál přes skutečnou inicializaci.
    """
    from app.database import schema

    real_init = schema._initialize_database

    def init_or_copy(db_path):
        target = Path(str(db_path))
        if str(db_path) != ":memory:" and not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(_template_db, target)
            return
        real_init(db_path)

    monkeypatch.setattr(schema, "_initialize_database", init_or_copy)
    yield
