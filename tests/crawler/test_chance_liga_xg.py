from __future__ import annotations

from app.crawler.chance_liga_xg import extract_xg_from_html, statistics_url


HTML = """
<table>
  <tr><th>Statistika</th><th>Domácí</th><th>Hosté</th></tr>
  <tr><td>xG</td><td>1,42</td><td>0,86</td></tr>
  <tr><td>xGOT</td><td>1,10</td><td>0,40</td></tr>
</table>
"""


def test_extract_xg_from_html_reads_home_and_away_values():
    result = extract_xg_from_html(HTML)

    assert result == (1.42, 0.86)


def test_extract_xg_ignores_xgot_row():
    html = """
    <table>
      <tr><td>xGOT</td><td>1,10</td><td>0,40</td></tr>
      <tr><td>xG</td><td>2,05</td><td>0,75</td></tr>
    </table>
    """

    assert extract_xg_from_html(html) == (2.05, 0.75)


def test_missing_or_ambiguous_xg_returns_none():
    assert extract_xg_from_html("") is None
    assert extract_xg_from_html("<p>Statistiky nejsou dostupné.</p>") is None
    assert extract_xg_from_html("<table><tr><td>xG</td><td>1,20</td></tr></table>") is None


def test_statistics_url_is_derived_from_match_detail():
    assert statistics_url("https://www.chanceliga.cz/zapas/8197-sk-sigma-olomouc-fc-hradec-kralove") == (
        "https://www.chanceliga.cz/zapas/statistiky/8197-sk-sigma-olomouc-fc-hradec-kralove"
    )
    assert statistics_url("https://www.chanceliga.cz/zapas/statistiky/8197-sk-sigma-olomouc-fc-hradec-kralove") == (
        "https://www.chanceliga.cz/zapas/statistiky/8197-sk-sigma-olomouc-fc-hradec-kralove"
    )
