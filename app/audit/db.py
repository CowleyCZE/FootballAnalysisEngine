import sqlite3
import logging

logger = logging.getLogger(__name__)

def init_audit_tables(db_path: str = "database/football.db"):
    """
    Inicializuje auditní tabulky. Používá kompatibilní schéma se schema.sql.
    Pokud tabulky již existují (vytvořené přes schema.sql), provede migrace sloupců.
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Vytvoření tabulky audit_runs — kompatibilní s oběma definicemi (schema.sql i audit/db.py)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS audit_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        audit_id TEXT,
        run_id TEXT,
        match_id INTEGER,
        ai_run_id TEXT,
        audit_score REAL,
        status TEXT NOT NULL,
        missing_data_count INTEGER NOT NULL DEFAULT 0,
        issues_count INTEGER NOT NULL DEFAULT 0,
        coverage_score REAL NOT NULL DEFAULT 0.0,
        executed_at TEXT,
        created_at TEXT
    );
    """)

    # Migrace: přidání chybějících sloupců
    cursor.execute("PRAGMA table_info(audit_runs)")
    existing = [r[1] for r in cursor.fetchall()]
    for col, col_type in [
        ("run_id", "TEXT"),
        ("ai_run_id", "TEXT"),
        ("audit_score", "REAL"),
        ("executed_at", "TEXT"),
        ("created_at", "TEXT"),
        ("missing_data_count", "INTEGER DEFAULT 0"),
        ("issues_count", "INTEGER DEFAULT 0"),
        ("coverage_score", "REAL DEFAULT 0.0"),
    ]:
        if col not in existing:
            try:
                cursor.execute(f"ALTER TABLE audit_runs ADD COLUMN {col} {col_type}")
            except sqlite3.OperationalError:
                pass

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS audit_issues (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        audit_id TEXT,
        audit_run_id INTEGER,
        rule_name TEXT,
        issue_type TEXT,
        severity TEXT NOT NULL,
        message TEXT,
        description TEXT,
        details_json TEXT,
        requires_research INTEGER NOT NULL DEFAULT 0,
        created_at TEXT
    );
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS audit_issue_evidence (
        audit_issue_id INTEGER NOT NULL,
        evidence_id INTEGER NOT NULL,
        PRIMARY KEY (audit_issue_id, evidence_id)
    );
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS audit_issue_claims (
        audit_issue_id INTEGER NOT NULL,
        claim_id INTEGER NOT NULL,
        PRIMARY KEY (audit_issue_id, claim_id)
    );
    """)

    conn.commit()
    conn.close()
    logger.info("Audit database tables initialized.")
