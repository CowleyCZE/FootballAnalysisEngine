import sqlite3
from typing import Optional
from urllib.parse import urlparse
from app.database.connection import get_connection
from app.crawler.models import ParsedDocument

def save_document_to_db(doc: ParsedDocument, raw_path: str, conn: Optional[sqlite3.Connection] = None) -> int:
    should_close = False
    if conn is None:
        conn = get_connection()
        should_close = True

    cursor = conn.cursor()

    try:
        domain = urlparse(doc.url).netloc

        # 1. Zajištění existence zdroje (Source)
        cursor.execute("SELECT id FROM sources WHERE domain = ?", (domain,))
        source_row = cursor.fetchone()
        if source_row:
            source_id = source_row["id"]
        else:
            cursor.execute(
                "INSERT INTO sources (domain, name, source_type) VALUES (?, ?, ?)",
                (domain, domain, "NEWS")
            )
            source_id = cursor.lastrowid

        # 2. Uložení dokumentu
        cursor.execute("""
            INSERT INTO documents (
                source_id, url, canonical_url, content_hash, title, description,
                language, published_at, retrieved_at, raw_path, quality_score, parser_version
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            source_id, doc.url, doc.canonical_url, doc.content_hash, doc.title, doc.description,
            doc.language, doc.published_at, doc.retrieved_at, raw_path, doc.quality_score, "1.0.0"
        ))
        
        doc_id = cursor.lastrowid
        if should_close:
            conn.commit()
        return doc_id
    except Exception as e:
        if should_close:
            conn.rollback()
        raise e
    finally:
        if should_close:
            conn.close()