"""Fáze 9 – parser musí z HTML vytáhnout datum publikace (jinak audit hlásí cutoff_violation)."""
import pytest

from app.parser.html_parser import HTMLParser

BODY = "<body><article><p>Jablonec před zápasem se Slavií bez zraněného obránce. Trenér potvrdil sestavu.</p></article></body>"


def _doc(head: str) -> str:
    return f"<html lang='cs'><head><title>x</title>{head}</head>{BODY}</html>"


@pytest.mark.parametrize("head,expected", [
    ('<meta property="article:published_time" content="2026-10-20T10:00:00+00:00">', "2026-10-20T10:00:00+00:00"),
    ('<meta itemprop="datePublished" content="2026-10-19">', "2026-10-19"),
    ('<meta name="date" content="2026-10-18T08:30:00Z">', "2026-10-18T08:30:00Z"),
    ('<script type="application/ld+json">{"@type":"NewsArticle","datePublished":"2026-10-17T07:00:00+02:00"}</script>',
     "2026-10-17T07:00:00+02:00"),
    ('<script type="application/ld+json">{"@graph":[{"@type":"WebPage"},{"@type":"Article","datePublished":"2026-10-16"}]}</script>',
     "2026-10-16"),
    ('<meta name="date" content="20. 10. 2026 14:30">', "2026-10-20T14:30:00"),
])
def test_published_at_from_structured_metadata(head, expected):
    assert HTMLParser().parse(_doc(head), "https://example.cz/a").published_at == expected


def test_published_at_from_time_tag():
    html = "<html><head><title>x</title></head><body><article><time datetime='2026-10-15T12:00:00Z'>včera</time><p>Text článku o zápase a sestavě týmu.</p></article></body></html>"
    assert HTMLParser().parse(html, "https://example.cz/a").published_at == "2026-10-15T12:00:00Z"


@pytest.mark.parametrize("head", [
    "",
    '<meta name="date" content="včera">',
    '<script type="application/ld+json">{broken json</script>',
    '<meta property="article:published_time" content="">',
])
def test_missing_or_unparseable_date_stays_none(head):
    assert HTMLParser().parse(_doc(head), "https://example.cz/a").published_at is None


def test_invalid_meta_falls_through_to_next_valid_source():
    head = '<meta property="article:published_time" content="nesmysl"><meta itemprop="datePublished" content="2026-10-14">'
    assert HTMLParser().parse(_doc(head), "https://example.cz/a").published_at == "2026-10-14"
