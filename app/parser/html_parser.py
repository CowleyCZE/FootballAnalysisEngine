import hashlib
import logging
import re
from datetime import datetime, timezone
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from app.crawler.models import ParsedDocument
from app.parser.text_cleaner import clean_text

logger = logging.getLogger(__name__)

_CZ_CHARS = set("áčďéěíňóřšťúůýžÁČĎÉĚÍŇÓŘŠŤÚŮÝŽ")


def detect_language(soup: BeautifulSoup, text: str) -> str:
    """Jazyk dokumentu: <html lang> / meta / og:locale, jinak heuristika (TODO 3.6)."""
    candidates = []
    html_tag = soup.find("html")
    if html_tag and html_tag.get("lang"):
        candidates.append(html_tag.get("lang"))
    for attrs in ({"http-equiv": re.compile("content-language", re.I)}, {"name": "language"}, {"property": "og:locale"}):
        tag = soup.find("meta", attrs=attrs)
        if tag and tag.get("content"):
            candidates.append(tag.get("content"))
    for cand in candidates:
        code = re.split(r"[-_]", str(cand).strip().lower())[0]
        if 2 <= len(code) <= 3 and code.isalpha():
            return code
    sample = text[:3000]
    letters = [c for c in sample if c.isalpha()]
    if letters:
        ratio = sum(1 for c in letters if c in _CZ_CHARS) / len(letters)
        if ratio >= 0.03:
            return "cs"
    return "en"


def _meta_content(soup: BeautifulSoup, *specs) -> str | None:
    for attrs in specs:
        tag = soup.find("meta", attrs=attrs)
        if tag and tag.get("content") and tag.get("content").strip():
            return tag.get("content").strip()
    return None


def extract_canonical(soup: BeautifulSoup, url: str) -> str:
    link = soup.find("link", attrs={"rel": lambda v: v and "canonical" in ([v] if isinstance(v, str) else v)})
    href = link.get("href") if link else None
    if not href:
        href = _meta_content(soup, {"property": "og:url"})
    if href and href.strip():
        return urljoin(url, href.strip())
    return url


def extract_author(soup: BeautifulSoup) -> str | None:
    author = _meta_content(soup, {"name": "author"}, {"property": "article:author"}, {"name": "article:author"})
    if author and not author.lower().startswith("http"):
        return author
    tag = soup.find(attrs={"itemprop": "author"}) or soup.find(attrs={"rel": "author"})
    if tag:
        name = tag.get("content") or tag.get_text(" ", strip=True)
        if name:
            return name.strip()
    return None

_PUBLISHED_META = (
    {"property": "article:published_time"},
    {"name": "article:published_time"},
    {"property": "og:article:published_time"},
    {"itemprop": "datePublished"},
    {"name": "datePublished"},
    {"name": "date"},
    {"name": "pubdate"},
    {"name": "publishdate"},
    {"name": "DC.date.issued"},
    {"name": "DC.date"},
    {"name": "dcterms.created"},
)


def _normalize_date(value) -> str | None:
    """Vrátí datum jen pokud je skutečně rozpoznatelné (ISO nebo české d. m. rrrr); nic se nedomýšlí."""
    text = str(value or "").strip()
    if not text:
        return None
    try:
        datetime.fromisoformat(text.replace("Z", "+00:00"))
        return text
    except ValueError:
        pass
    m = re.match(r"^(\d{1,2})\.\s*(\d{1,2})\.\s*(\d{4})(?:\s+(\d{1,2}):(\d{2}))?$", text)
    if m:
        day, month, year, hour, minute = m.groups()
        try:
            return datetime(int(year), int(month), int(day), int(hour or 0), int(minute or 0)).isoformat()
        except ValueError:
            return None
    return None


def _jsonld_dates(soup: BeautifulSoup):
    import json
    for tag in soup.find_all("script", attrs={"type": re.compile(r"ld\+json", re.I)}):
        try:
            data = json.loads(tag.string or tag.get_text() or "")
        except (ValueError, TypeError):
            continue
        stack = [data]
        while stack:
            item = stack.pop(0)
            if isinstance(item, list):
                stack.extend(item)
            elif isinstance(item, dict):
                if item.get("datePublished"):
                    yield item["datePublished"]
                stack.extend(v for v in item.values() if isinstance(v, (list, dict)))


def extract_published_at(soup: BeautifulSoup) -> str | None:
    """Datum publikace ze strukturovaných metadat (meta, JSON-LD, itemprop, <time>). Bez zdroje data = None."""
    for attrs in _PUBLISHED_META:
        for tag in soup.find_all("meta", attrs=attrs):
            date = _normalize_date(tag.get("content"))
            if date:
                return date
    for raw in _jsonld_dates(soup):
        date = _normalize_date(raw)
        if date:
            return date
    for tag in soup.find_all(attrs={"itemprop": "datePublished"}):
        date = _normalize_date(tag.get("datetime") or tag.get("content") or tag.get_text(" ", strip=True))
        if date:
            return date
    for tag in soup.find_all("time"):
        date = _normalize_date(tag.get("datetime"))
        if date:
            return date
    return None


class HTMLParser:
    def __init__(self) -> None:
        # lxml is faster, but it is an optional BeautifulSoup backend. A clean
        # notebook install must still work with bs4's standard-library parser.
        try:
            import lxml  # noqa: F401
            self.backend = "lxml"
        except ImportError:
            self.backend = "html.parser"
            logger.warning("lxml není nainstalováno; HTML research používá html.parser.")

    def parse(self, html: str, url: str) -> ParsedDocument:
        try:
            soup = BeautifulSoup(html, self.backend)
        except Exception as exc:
            if self.backend == "html.parser":
                raise
            logger.warning("Parser lxml selhal (%s); používám html.parser.", exc)
            self.backend = "html.parser"
            soup = BeautifulSoup(html, self.backend)

        # Metadata z <head> a <html> se čtou před odstraněním prvků (TODO 3.6)
        canonical_url = extract_canonical(soup, url)
        author = extract_author(soup)
        published_at = extract_published_at(soup)  # před decompose() (JSON-LD je v <script>)

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

        # Extraktor hlavního obsahu
        main_content = soup.find("article") or soup.find("main") or soup.find("div", attrs={"role": "main"}) or soup.body
        raw_text = main_content.get_text() if main_content else ""
        cleaned_text = clean_text(raw_text)

        word_count = len(cleaned_text.split())
        content_hash = hashlib.sha256(cleaned_text.encode("utf-8")).hexdigest()

        # Základní skóre kvality získaného textu
        quality_score = 1.0 if word_count > 100 else (word_count / 100.0)

        language = detect_language(soup, cleaned_text)

        return ParsedDocument(
            url=url,
            canonical_url=canonical_url,
            title=title,
            description=description,
            author=author,
            published_at=published_at,
            retrieved_at=datetime.now(timezone.utc).isoformat(),
            language=language,
            text=cleaned_text,
            word_count=word_count,
            content_hash=content_hash,
            quality_score=quality_score
        )
