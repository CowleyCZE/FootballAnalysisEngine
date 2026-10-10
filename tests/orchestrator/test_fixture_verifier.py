import json
import sqlite3
from datetime import datetime, timezone

import pytest

from app.database.schema import initialize_database
from app.orchestrator.fixture_verifier import FixtureVerifier
from app.search.models import SearchResult


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


@pytest.mark.parametrize(
    "url",
    ["https://www.chanceliga.cz/zapasy", "https://sparta.cz/zapas/123"],
)
def test_official_exact_fixture_resolves_and_records_evidence(fixture_db):
    verifier = FixtureVerifier(
        db_path=fixture_db,
        search_engine=FakeSearchEngine([
            result("https://www.chanceliga.cz/zapasy/1", "AC Sparta Praha - FK Pardubice",
                   "AC Sparta Praha - FK Pardubice, Chance Liga, 11.10.2026, 18:00"),
        ]),
        official_domains={"chanceliga.cz"},
    )
    import asyncio
    report = asyncio.run(verifier.verify(7))
    assert report["outcome"] == "UNVERIFIED"
    with sqlite3.connect(fixture_db) as conn:
        assert conn.execute("SELECT status FROM matches WHERE id=7").fetchone()[0] == "scheduled"
        audit = conn.execute(
            "SELECT outcome,evidence_json FROM fixture_verification_runs WHERE match_id=7"
        ).fetchone()
        assert audit[0] == "UNVERIFIED"
        assert "chanceliga.cz" in audit[1]


@pytest.mark.parametrize(
    "title,content",
    [
        ("Sparta - Pardubice", "AC Sparta Praha vs FK Pardubice, Chance Liga, 18.10.2026"),
        ("Sparta - Pardubice", "AC Sparta Praha vs FK Pardubice, Premier League, 11.10.2026"),
        ("Sparta news", "AC Sparta Praha transfer news. Chance Liga."),
        ("Sparta - Pardubice", "FK Pardubice vs AC Sparta Praha, Chance Liga, 11.10.2026"),
    ],
)
def test_invalid_fixture_does_not_resolve(fixture_db, title, content):
    verifier = FixtureVerifier(
        db_path=fixture_db,
        search_engine=FakeSearchEngine([
            result("https://www.chanceliga.cz/zapasy", title, content),
        ]),
        official_domains={"chanceliga.cz"},
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
                   "AC Sparta Praha vs FK Pardubice, Chance Liga, 11.10.2026"),
        ]),
        official_domains={"chanceliga.cz"},
    )
    import asyncio
    report = asyncio.run(verifier.verify(7))
    assert report["outcome"] == "UNVERIFIED"
    assert report["rejected_sources"][0]["official_domain"] is False

def test_requires_two_independent_official_domains(fixture_db):
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


def test_swapped_home_away_order_cannot_verify(fixture_db):
    verifier = FixtureVerifier(
        db_path=fixture_db,
        search_engine=FakeSearchEngine([
            result("https://www.chanceliga.cz/zapasy/1", "Fixture 1",
                   "AC Sparta Praha - FK Pardubice, Chance Liga, 11.10.2026, 18:00"),
            result("https://www.fotbal.cz/zapasy/1", "Fixture 2",
                   "FK Pardubice - AC Sparta Praha, Chance Liga, 11.10.2026, 18:00"),
        ]),
        official_domains={"chanceliga.cz", "fotbal.cz"},
    )
    import asyncio
    report = asyncio.run(verifier.verify(7))
    assert report["outcome"] == "UNVERIFIED"
    with sqlite3.connect(fixture_db) as conn:
        assert conn.execute("SELECT status FROM matches WHERE id=7").fetchone()[0] == "scheduled"
