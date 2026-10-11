import argparse
from pathlib import Path
import sys

# Direct execution (`python scripts/init_database.py`) puts `scripts/`, not
# the repository root, on sys.path. Add the root before importing the app.
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.database.schema import initialize_database


def init_db(db_path=None):
    base_dir = REPO_ROOT
    target_db = Path(db_path) if db_path is not None else base_dir / "database" / "football.db"
    target_db.parent.mkdir(parents=True, exist_ok=True)
    print(f"Inicializuji databázi v: {target_db}")
    initialize_database(str(target_db))
    print("[OK] Databázové schéma úspěšně aplikováno!")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Inicializuje databázové schéma Football Analysis Engine.")
    parser.add_argument("--db-path", help="Volitelná cesta k databázi (výchozí: database/football.db).")
    args = parser.parse_args()
    init_db(args.db_path)
