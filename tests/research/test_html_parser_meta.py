"""TODO 3.6 – HTMLParser: jazyk, canonical, author."""
from app.parser.html_parser import HTMLParser

CZ_HTML = """<html lang="cs-CZ"><head><title>Sparta před derby</title>
<link rel="canonical" href="/clanek/sparta-derby">
<meta name="author" content="Jan Novák">
<meta property="article:published_time" content="2026-10-20T10:00:00+00:00">
</head><body><article><p>Sparta před derby bez zraněného útočníka. Trenér potvrdil sestavu a taktiku.</p></article></body></html>"""

EN_HTML = """<html lang="en"><head><title>Preview</title></head>
<body><article><p>The visitors are unbeaten in five matches and expect a tight game.</p></article></body></html>"""

NO_LANG_CZ = "<html><head><title>x</title></head><body><article><p>Příliš žluťoučký kůň úpěl ďábelské ódy, zranění hráčů a změny v sestavě.</p></article></body></html>"

NO_LANG_EN = "<html><head><title>x</title></head><body><article><p>Plain english sentence about the next match and the weather forecast.</p></article></body></html>"


def test_language_from_html_lang():
    p = HTMLParser()
    assert p.parse(CZ_HTML, "https://www.sparta.cz/a").language == "cs"
    assert p.parse(EN_HTML, "https://example.com/a").language == "en"


def test_language_heuristic_without_meta():
    p = HTMLParser()
    assert p.parse(NO_LANG_CZ, "https://example.cz/a").language == "cs"
    assert p.parse(NO_LANG_EN, "https://example.com/a").language == "en"


def test_canonical_resolved_against_url_and_author_extracted():
    doc = HTMLParser().parse(CZ_HTML, "https://www.sparta.cz/a?utm=1")
    assert doc.canonical_url == "https://www.sparta.cz/clanek/sparta-derby"
    assert doc.author == "Jan Novák"
    assert doc.published_at == "2026-10-20T10:00:00+00:00"


def test_missing_canonical_falls_back_to_url_and_no_author():
    doc = HTMLParser().parse(EN_HTML, "https://example.com/a")
    assert doc.canonical_url == "https://example.com/a"
    assert doc.author is None
