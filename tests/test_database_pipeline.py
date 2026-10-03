import sqlite3
import uuid

from app.database.connection import get_connection
from app.database.repository import save_document_to_db
from app.crawler.models import ParsedDocument


def test_evidence_first_pipeline():
    conn = get_connection()
    cursor = conn.cursor()
    suffix = uuid.uuid4().hex[:8]
    run_key = f"RUN-TEST-{suffix}"
    home_name = f"AC Sparta Praha {suffix}"
    away_name = f"SK Slavia Praha {suffix}"
    home_norm = f"sparta_praha_{suffix}"
    away_norm = f"slavia_praha_{suffix}"
    url = f"https://www.sport.cz/clanek/sparta-zraneni-dostal-{suffix}"
    raw_path = f"data/raw/HASH_DOSTAL_INJURY_{suffix}.html"
    content_hash = f"HASH_DOSTAL_INJURY_{suffix}"

    try:
        cursor.execute("INSERT INTO runs (run_id, status, started_at) VALUES (?, 'RUNNING', '2026-10-02T12:00:00Z')", (run_key,))
        run_id = cursor.lastrowid
        cursor.execute("INSERT INTO teams (name, normalized_name) VALUES (?, ?)", (home_name, home_norm))
        home_id = cursor.lastrowid
        cursor.execute("INSERT INTO teams (name, normalized_name) VALUES (?, ?)", (away_name, away_norm))
        away_id = cursor.lastrowid
        cursor.execute(
            "INSERT INTO matches (competition, season, home_team_id, away_team_id) VALUES ('Chance Liga', '2026/27', ?, ?)",
            (home_id, away_id),
        )
        match_id = cursor.lastrowid

        doc = ParsedDocument(
            url=url,
            canonical_url=url,
            title="Sparta před derby: Klíčový útočník mimo hru",
            description="Detailní zpráva o zranění",
            author="Jan Novák",
            published_at="2026-10-01T10:00:00Z",
            retrieved_at="2026-10-02T12:00:00Z",
            language="cs",
            text="Útočník Dostál má zraněný kotník a do zápasu nenastoupí.",
            word_count=10,
            content_hash=content_hash,
            quality_score=1.0,
        )
        doc_id = save_document_to_db(doc, raw_path, conn=conn)
        cursor.execute(
            "INSERT INTO evidence (document_id, evidence_type, quoted_text, locator) VALUES (?, 'QUOTE', ?, 'paragraph: 1')",
            (doc_id, "Útočník Dostál má zraněný kotník a do zápasu nenastoupí."),
        )
        evidence_id = cursor.lastrowid
        cursor.execute(
            "INSERT INTO claims (run_id, match_id, claim_text, claim_type, status, confidence) VALUES (?, ?, 'Útočník Dostál nenastoupí kvůli zranění.', 'INJURY', 'SUPPORTED', 0.95)",
            (run_id, match_id),
        )
        claim_id = cursor.lastrowid
        cursor.execute("INSERT INTO claim_evidence (claim_id, evidence_id, relationship) VALUES (?, ?, 'SUPPORTS')", (claim_id, evidence_id))

        cursor.execute(
            """
            SELECT c.claim_text, c.status, e.quoted_text, d.url, d.published_at, d.raw_path
            FROM claims c
            JOIN claim_evidence ce ON ce.claim_id = c.id
            JOIN evidence e ON e.id = ce.evidence_id
            JOIN documents d ON d.id = e.document_id
            WHERE c.id = ?
            """,
            (claim_id,),
        )
        row = cursor.fetchone()

        assert row is not None
        assert row["claim_text"] == "Útočník Dostál nenastoupí kvůli zranění."
        assert row["quoted_text"] == "Útočník Dostál má zraněný kotník a do zápasu nenastoupí."
        assert row["raw_path"] == raw_path
    finally:
        conn.rollback()
        conn.close()
