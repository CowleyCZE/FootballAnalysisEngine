from __future__ import annotations

from app.crawler.chance_liga_history import parse_schedule_html, season_label


HTML = """
<table>
  <tr><th>1.kolo</th></tr>
  <tr>
    <td>pá, 19/07/2024</td>
    <td>AC Sparta Praha</td>
    <td>2:1</td>
    <td>FK Pardubice</td>
  </tr>
  <tr>
    <td>so, 20/07/2024</td>
    <td>FK Jablonec</td>
    <td>-:-</td>
    <td>FK Mladá Boleslav</td>
  </tr>
</table>
"""

HTML_WITH_LINK = """
<table>
  <tr><th>1.kolo</th></tr>
  <tr>
    <td>pá, 19/07/2024</td>
    <td><a href="/zapas/8197-sk-sigma-olomouc-fc-hradec-kralove">SK Sigma Olomouc</a></td>
    <td>2:1</td>
    <td>FC Hradec Králové</td>
  </tr>
</table>
"""


def test_parse_schedule_html_extracts_finished_and_scheduled_matches():
    records = parse_schedule_html(HTML, season_label(2024))

    assert len(records) == 2

    finished = records[0]
    assert finished["status"] == "FINISHED"
    assert finished["home_team"] == "AC Sparta Praha"
    assert finished["away_team"] == "FK Pardubice"
    assert finished["home_goals"] == 2
    assert finished["away_goals"] == 1
    assert finished["scheduled_at"].startswith("2024-07-19")
    assert finished["external_match_id"].startswith("CLH_")

    scheduled = records[1]
    assert scheduled["status"] == "SCHEDULED"
    assert scheduled["home_goals"] is None
    assert scheduled["away_goals"] is None


def test_external_ids_are_stable():
    first = parse_schedule_html(HTML, season_label(2024))[0]
    second = parse_schedule_html(HTML, season_label(2024))[0]

    assert first["external_match_id"] == second["external_match_id"]


def test_missing_xg_is_not_invented():
    records = parse_schedule_html(HTML, season_label(2024))

    assert all(record["home_xg"] is None for record in records)
    assert all(record["away_xg"] is None for record in records)


def test_match_detail_url_is_captured_when_available():
    records = parse_schedule_html(HTML_WITH_LINK, season_label(2024))

    assert len(records) == 1
    assert records[0]["match_url"] == (
        "https://www.chanceliga.cz/zapas/8197-sk-sigma-olomouc-fc-hradec-kralove"
    )
