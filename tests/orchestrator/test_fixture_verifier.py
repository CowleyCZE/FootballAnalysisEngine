import sqlite3

import pytest

from app.database.schema import initialize_database
from app.orchestrator.fixture_verifier import FixtureVerifier


class FakeSearXNGClient:
    def __init__(self, results):
        self.results = results
        self.queries = []

    async def search(self, query, language="all", page=1, time_range=None):
        self.queries.append(query)
        return {"results": self.results}


class FakeSearchEngine:
    def __init__(self, results):
        self.client = FakeSearXNGClient(results)


@pytest.fixture
def fixture_db(tmp_path):
    db = str(tmp_path / "football.db")
    initialize_database(db)
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO competitions(id,name,country) VALUES(1,'Chance Liga','Czech Republic')")
        conn.execute("INSERT INTO teams(id,name,normalized_name) VALUES(1,'AC Sparta Praha','ac_sparta_praha')")
        conn.execute("INSERT INTO teams(id,name,normalized_name) VALUES(2,'FK Pardubice','fk_pardubice')")
        conn.execute(
            """INSERT INTO matches(id,competition,competition_id,season,home_team_id,away_team_id,
                   scheduled_at,status) VALUES(7,'Chance Liga',1,'2026/2027',1,2,
                   '2026-10-11T18:00:00+02:00','scheduled')"""
        )
    return db


def result(url, title, content):
    return {"url": url, "title": title, "content": content, "publishedDate": None}


def test_two_independent_official_sources_resolve_and_record_evidence(fixture_db):
    verifier = FixtureVerifier(
        db_path=fixture_db,
        search_engine=FakeSearchEngine([
            result("https://www.chanceliga.cz/zapasy/1", "AC Sparta Praha - FK Pardubice",
                   "AC Sparta Praha - FK Pardubice, Chance Liga, 11.10.2026, 18:00"),
            result("https://www.fotbal.cz/zapasy/2", "AC Sparta Praha - FK Pardubice",
                   "AC Sparta Praha - FK Pardubice, Chance Liga, 11.10.2026, 18:00"),
        ]),
        official_domains={"chanceliga.cz", "fotbal.cz"},
    )
    import asyncio
    report = asyncio.run(verifier.verify(7))
    assert report["outcome"] == "RESOLVED"
    with sqlite3.connect(fixture_db) as conn:
        assert conn.execute("SELECT status FROM matches WHERE id=7").fetchone()[0] == "RESOLVED"
        audit = conn.execute(
            "SELECT outcome,evidence_json FROM fixture_verification_runs WHERE match_id=7"
        ).fetchone()
        assert audit[0] == "RESOLVED"
        assert "chanceliga.cz" in audit[1]


@pytest.mark.parametrize(
    "title,content",
    [
        ("Sparta - Pardubice", "AC Sparta Praha vs FK Pardubice, Chance Liga, 18.10.2026, 18:00"),
        ("Sparta - Pardubice", "AC Sparta Praha vs FK Pardubice, Premier League, 11.10.2026, 18:00"),
        ("Sparta news", "AC Sparta Praha transfer news. Chance Liga, 11.10.2026, 18:00"),
        ("Sparta - Pardubice", "FK Pardubice - AC Sparta Praha, Chance Liga, 11.10.2026, 18:00"),
        ("Sparta - Pardubice", "AC Sparta Praha - FK Pardubice, Chance Liga, 11.10.2026, 19:00"),
    ],
)
def test_wrong_or_incomplete_fixture_does_not_resolve(fixture_db, title, content):
    verifier = FixtureVerifier(
        db_path=fixture_db,
        search_engine=FakeSearchEngine([
            result("https://www.chanceliga.cz/zapasy", title, content),
            result("https://www.fotbal.cz/zapasy", title, content),
        ]),
        official_domains={"chanceliga.cz", "fotbal.cz"},
    )
    import asyncio
    report = asyncio.run(verifier.verify(7))
    assert report["outcome"] == "UNVERIFIED"
    with sqlite3.connect(fixture_db) as conn:
        assert conn.execute("SELECT status FROM matches WHERE id=7").fetchone()[0] == "scheduled"


def test_unofficial_article_cannot_resolve(fixture_db):
    verifier = FixtureVerifier(
        db_path=fixture_db,
        search_engine=FakeSearchEngine([
            result("https://example.com/news", "Match preview",
                   "AC Sparta Praha - FK Pardubice, Chance Liga, 11.10.2026, 18:00"),
            result("https://example.org/news", "Match preview",
                   "AC Sparta Praha - FK Pardubice, Chance Liga, 11.10.2026, 18:00"),
        ]),
        official_domains={"chanceliga.cz", "fotbal.cz"},
    )
    import asyncio
    report = asyncio.run(verifier.verify(7))
    assert report["outcome"] == "UNVERIFIED"
    assert all(source["official_domain"] is False for source in report["rejected_sources"])


def test_two_urls_from_same_official_domain_are_insufficient(fixture_db):
    verifier = FixtureVerifier(
        db_path=fixture_db,
        search_engine=FakeSearchEngine([
            result("https://www.chanceliga.cz/zapasy/123", "Fixture 1",
                   "AC Sparta Praha - FK Pardubice, Chance Liga, 11.10.2026, 18:00"),
            result("https://www.chanceliga.cz/zapasy/456", "Fixture 2",
                   "AC Sparta Praha - FK Pardubice, Chance Liga, 11.10.2026, 18:00"),
        ]),
        official_domains={"chanceliga.cz"},
    )
    import asyncio
    report = asyncio.run(verifier.verify(7))
    assert report["outcome"] == "UNVERIFIED"
    with sqlite3.connect(fixture_db) as conn:
        assert conn.execute("SELECT status FROM matches WHERE id=7").fetchone()[0] == "scheduled"


@pytest.mark.parametrize(
    "value,expected",
    [
        ("11.10.2026, 18:00", (2026, 10, 11, 18, 0)),
        ("11. 10. 2026. 18:00", (2026, 10, 11, 18, 0)),
        ("Sun, 11. 10. 2026. 18:00, AC Sparta Praha - FK Pardubice", (2026, 10, 11, 18, 0)),
        ("2026-10-11T18:00:00+02:00", (2026, 10, 11, 18, 0)),
    ],
)
def test_candidate_datetime_parses_common_schedule_formats(value, expected):
    parsed = FixtureVerifier._parse_candidate_datetime(value)
    assert parsed is not None
    assert (parsed.year, parsed.month, parsed.day, parsed.hour, parsed.minute) == expected


def test_candidate_datetimes_keeps_later_target_after_old_fixture():
    parsed = FixtureVerifier._parse_candidate_datetimes(
        "Previous match 20.09.2026, 15:00; next match Sun, 11. 10. 2026. 18:00"
    )
    assert [(item.year, item.month, item.day, item.hour, item.minute) for item in parsed] == [
        (2026, 9, 20, 15, 0),
        (2026, 10, 11, 18, 0),
    ]


def test_fixture_pair_ignores_earlier_away_team_mention():
    text = "FK Pardubice schedule. AC Sparta Praha – FK Pardubice, Chance Liga"
    assert FixtureVerifier._fixture_pair_ok(text, "AC Sparta Praha", "FK Pardubice")


def test_fixture_pair_rejects_unrelated_team_mentions():
    text = "AC Sparta Praha news and FK Pardubice news are separate topics."
    assert not FixtureVerifier._fixture_pair_ok(text, "AC Sparta Praha", "FK Pardubice")
