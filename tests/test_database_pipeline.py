import pytest
import sqlite3
from app.database.connection import get_connection, init_database_schema
from app.database.repository import save_document_to_db
from app.crawler.models import ParsedDocument

@pytest.fixture
def isolated_conn(tmp_path):
    """Vrátí izolované sqlite3.Row spojení s novou tmp databází."""
    db_file = str(tmp_path / "test_pipeline.db")
    init_database_schema(db_file)
    conn = sqlite3.connect(db_file)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()

def test_evidence_first_pipeline(isolated_conn):
    conn = isolated_conn
    cursor = conn.cursor()

    # 1. Vytvoření Runu
    cursor.execute("INSERT INTO runs (run_id, status, started_at) VALUES ('RUN-TEST-001', 'RUNNING', '2026-10-02T12:00:00Z')")
    run_id = cursor.lastrowid

    # 2. Vytvoření Týmů a Zápasu
    cursor.execute("INSERT INTO teams (name, normalized_name) VALUES ('AC Sparta Praha', 'sparta_praha')")
    home_id = cursor.lastrowid
    cursor.execute("INSERT INTO teams (name, normalized_name) VALUES ('SK Slavia Praha', 'slavia_praha')")
    away_id = cursor.lastrowid

    cursor.execute("INSERT INTO matches (competition, season, home_team_id, away_team_id) VALUES ('Chance Liga', '2026/27', ?, ?)", (home_id, away_id))
    match_id = cursor.lastrowid

    # 3. Uložení Testovacího Dokumentu s předáním conn
    doc = ParsedDocument(
        url="https://www.sport.cz/clanek/sparta-zraneni-dostal",
        canonical_url="https://www.sport.cz/clanek/sparta-zraneni-dostal",
        title="Sparta před derby: Klíčový útočník mimo hru",
        description="Detailní zpráva o zranění",
        author="Jan Novák",
        published_at="2026-10-01T10:00:00Z",
        retrieved_at="2026-10-02T12:00:00Z",
        language="cs",
        text="Útočník Dostál má zraněný kotník a do zápasu nenastoupí.",
        word_count=10,
        content_hash="HASH_DOSTAL_INJURY_123",
        quality_score=1.0
    )
    doc_id = save_document_to_db(doc, "data/raw/HASH_DOSTAL_INJURY_123.html", conn=conn)

    # 4. Vytvoření Evidence
    cursor.execute("""
        INSERT INTO evidence (document_id, evidence_type, quoted_text, locator)
        VALUES (?, 'QUOTE', 'Útočník Dostál má zraněný kotník a do zápasu nenastoupí.', 'paragraph: 1')
    """, (doc_id,))
    evidence_id = cursor.lastrowid

    # 5. Vytvoření Claimu
    cursor.execute("""
        INSERT INTO claims (run_id, match_id, claim_text, claim_type, status, confidence)
        VALUES (?, ?, 'Útočník Dostál nenastoupí kvůli zranění.', 'INJURY', 'SUPPORTED', 0.95)
    """, (run_id, match_id))
    claim_id = cursor.lastrowid

    # 6. Propojení Claim <-> Evidence
    cursor.execute("INSERT INTO claim_evidence (claim_id, evidence_id, relationship) VALUES (?, ?, 'SUPPORTS')", (claim_id, evidence_id))
    conn.commit()

    # 7. SQL VERIFIKACE AUDITABILITY
    cursor.execute("""
        SELECT
            c.claim_text,
            c.status,
            e.quoted_text,
            d.url,
            d.published_at,
            d.raw_path
        FROM claims c
        JOIN claim_evidence ce ON ce.claim_id = c.id
        JOIN evidence e ON e.id = ce.evidence_id
        JOIN documents d ON d.id = e.document_id
        WHERE c.id = ?
    """, (claim_id,))
    row = cursor.fetchone()

    assert row is not None
    assert row["claim_text"] == "Útočník Dostál nenastoupí kvůli zranění."
    assert row["quoted_text"] == "Útočník Dostál má zraněný kotník a do zápasu nenastoupí."
    assert row["raw_path"] == "data/raw/HASH_DOSTAL_INJURY_123.html"
    print("\n[OK] Evidence-First Audit trail úspěšně ověřen!")

if __name__ == "__main__":
    pytest.main([__file__, "-v"])