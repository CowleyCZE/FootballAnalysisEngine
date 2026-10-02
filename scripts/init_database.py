import sqlite3
from pathlib import Path

def init_db():
    base_dir = Path(__file__).parent.parent
    db_dir = base_dir / "database"
    db_dir.mkdir(exist_ok=True)
    
    db_path = db_dir / "football.db"
    schema_path = db_dir / "schema.sql"

    print(f"Inicializuji databázi v: {db_path}")
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")

    with open(schema_path, "r", encoding="utf-8") as f:
        schema_sql = f.read()

    conn.executescript(schema_sql)
    conn.commit()
    conn.close()
    print("[OK] Databázové schéma úspěšně aplikováno!")

if __name__ == "__main__":
    init_db()