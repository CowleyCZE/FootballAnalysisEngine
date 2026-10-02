import hashlib
from datetime import datetime, timezone
from bs4 import BeautifulSoup
from app.crawler.models import ParsedDocument
from app.parser.text_cleaner import clean_text

class HTMLParser:
    def parse(self, html: str, url: str) -> ParsedDocument:
        soup = BeautifulSoup(html, "lxml")

        # Odstranění nežádoucích prvků (script, style, iframe, nav...)
        for tag in soup(["script", "style", "noscript", "iframe", "svg", "nav", "footer", "header"]):
            tag.decompose()

        # Získání titulku
        title = soup.title.string.strip() if soup.title and soup.title.string else None

        # Získání metadata (published_at, author, description)
        description = None
        desc_tag = soup.find("meta", attrs={"name": "description"}) or soup.find("meta", attrs={"property": "og:description"})
        if desc_tag:
            description = desc_tag.get("content")

        published_at = None
        time_tag = soup.find("meta", attrs={"property": "article:published_time"}) or soup.find("time")
        if time_tag:
            published_at = time_tag.get("content") or time_tag.get("datetime")

        # Extraktor hlavního obsahu
        main_content = soup.find("article") or soup.find("main") or soup.find("div", attrs={"role": "main"}) or soup.body
        raw_text = main_content.get_text() if main_content else ""
        cleaned_text = clean_text(raw_text)

        word_count = len(cleaned_text.split())
        content_hash = hashlib.sha256(cleaned_text.encode("utf-8")).hexdigest()

        # Základní skóre kvality získaného textu
        quality_score = 1.0 if word_count > 100 else (word_count / 100.0)

        return ParsedDocument(
            url=url,
            canonical_url=url,
            title=title,
            description=description,
            author=None,
            published_at=published_at,
            retrieved_at=datetime.now(timezone.utc).isoformat(),
            language="cs",
            text=cleaned_text,
            word_count=word_count,
            content_hash=content_hash,
            quality_score=quality_score
        )