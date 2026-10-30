"""TODO 11.20: rozšířené rozpoznání data publikace; nic se nedomýšlí."""
import pytest
from bs4 import BeautifulSoup

from app.parser.html_parser import _normalize_date, extract_published_at


def _soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")


@pytest.mark.parametrize("text,expected", [
    ("24. října 2026", "2026-10-24T00:00:00"),
    ("24 října 2026 18:30", "2026-10-24T18:30:00"),
    ("1. ledna 2026", "2026-01-01T00:00:00"),
    ("5. září 2026", "2026-09-05T00:00:00"),
    ("24 October 2026", "2026-10-24T00:00:00"),
    ("October 24, 2026", "2026-10-24T00:00:00"),
    ("October 3rd, 2026", "2026-10-03T00:00:00"),
])
def test_named_month_dates_are_parsed(text, expected):
    assert _normalize_date(text) == expected


@pytest.mark.parametrize("text", [
    "před 2 hodinami", "včera", "31. února 2026", "října 2026", "24. října", "Oct 24", "last week", "",
])
def test_unverifiable_or_invalid_dates_are_rejected(text):
    assert _normalize_date(text) is None


def test_additional_meta_names():
    html = '<head><meta property="og:published_time" content="2026-10-20T10:00:00Z"></head>'
    assert extract_published_at(_soup(html)) == "2026-10-20T10:00:00Z"


def test_time_text_without_datetime_is_not_used():
    # Text <time> může být datum zápasu, ne publikace.
    assert extract_published_at(_soup("<time>24. října 2026</time>")) is None


def test_no_date_returns_none():
    assert extract_published_at(_soup("<p>Sparta vyhrála.</p>")) is None
