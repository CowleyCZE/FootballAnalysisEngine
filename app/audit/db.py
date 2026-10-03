import sqlite3
import logging

logger = logging.getLogger(__name__)

def init_audit_tables(db_path: str = "database/football.db"):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS audit_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id TEXT NOT NULL,
        match_id INTEGER,
        ai_run_id TEXT,
        audit_score REAL,
        status TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS audit_issues (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        audit_run_id INTEGER NOT NULL,
        issue_type TEXT NOT NULL,
        severity TEXT NOT NULL,
        description TEXT NOT NULL,
        requires_research INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        FOREIGN KEY (audit_run_id) REFERENCES audit_runs(id)
    );
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS audit_issue_evidence (
        audit_issue_id INTEGER NOT NULL,
        evidence_id INTEGER NOT NULL,
        PRIMARY KEY (audit_issue_id, evidence_id),
        FOREIGN KEY (audit_issue_id) REFERENCES audit_issues(id),
        FOREIGN KEY (evidence_id) REFERENCES evidence(id)
    );
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS audit_issue_claims (
        audit_issue_id INTEGER NOT NULL,
        claim_id INTEGER NOT NULL,
        PRIMARY KEY (audit_issue_id, claim_id),
        FOREIGN KEY (audit_issue_id) REFERENCES audit_issues(id),
        FOREIGN KEY (claim_id) REFERENCES claims(id)
    );
    """)

    conn.commit()
    conn.close()
    logger.info("Audit database tables initialized.")
