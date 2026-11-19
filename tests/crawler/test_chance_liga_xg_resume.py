from __future__ import annotations

import json

import pytest

from app.crawler import chance_liga_xg
from app.crawler.chance_liga_xg import enrich_records_with_xg

URL_A = "https://www.chanceliga.cz/zapas/1-a-b"
URL_B = "https://www.chanceliga.cz/zapas/2-c-d"
URL_C = "https://www.chanceliga.cz/zapas/3-e-f"

XG = {
    URL_A: (1.1, 0.4),
    URL_B: (2.2, 0.9),
    URL_C: (0.7, 1.3),
}


def _records(urls):
    return [{"match_url": url} for url in urls]


@pytest.fixture
def fake_fetch(monkeypatch):
    calls: list[str] = []

    async def _fake(match_url, client, max_attempts=4):
        calls.append(match_url)
        return XG.get(match_url)

    monkeypatch.setattr(chance_liga_xg, "fetch_match_xg", _fake)
    return calls


@pytest.mark.asyncio
async def test_second_run_uses_checkpoint_without_fetching(tmp_path, fake_fetch):
    checkpoint = tmp_path / "xg_checkpoint.json"

    report = await enrich_records_with_xg(_records([URL_A, URL_B]), object(), checkpoint_path=str(checkpoint))

    assert report["xg_fetched_now"] == 2
    assert report["xg_resumed"] == 0
    assert len(json.loads(checkpoint.read_text(encoding="utf-8"))) == 2
    assert fake_fetch == [URL_A, URL_B]

    fake_fetch.clear()
    records = _records([URL_A, URL_B])
    report2 = await enrich_records_with_xg(records, object(), checkpoint_path=str(checkpoint))

    assert fake_fetch == []
    assert report2["xg_resumed"] == 2
    assert report2["xg_fetched_now"] == 0
    assert report2["xg_enriched"] == 2
    assert (records[0]["home_xg"], records[0]["away_xg"]) == XG[URL_A]
    assert (records[1]["home_xg"], records[1]["away_xg"]) == XG[URL_B]


@pytest.mark.asyncio
async def test_resume_after_partial_run_fetches_only_missing(tmp_path, fake_fetch):
    checkpoint = tmp_path / "xg_checkpoint.json"

    await enrich_records_with_xg(_records([URL_A, URL_B]), object(), checkpoint_path=str(checkpoint))
    fake_fetch.clear()

    report = await enrich_records_with_xg(_records([URL_A, URL_B, URL_C]), object(), checkpoint_path=str(checkpoint))

    assert fake_fetch == [URL_C]
    assert report["xg_resumed"] == 2
    assert report["xg_fetched_now"] == 1
    assert report["xg_enriched"] == 3


@pytest.mark.asyncio
async def test_corrupted_checkpoint_starts_fresh(tmp_path, fake_fetch):
    checkpoint = tmp_path / "xg_checkpoint.json"
    checkpoint.write_text("{not valid json", encoding="utf-8")

    report = await enrich_records_with_xg(_records([URL_A]), object(), checkpoint_path=str(checkpoint))

    assert report["xg_fetched_now"] == 1
    assert report["xg_resumed"] == 0
    assert json.loads(checkpoint.read_text(encoding="utf-8")) == {URL_A: [1.1, 0.4]}


@pytest.mark.asyncio
async def test_missing_checkpoint_file_behaves_as_empty(tmp_path, fake_fetch):
    checkpoint = tmp_path / "nested" / "xg_checkpoint.json"

    report = await enrich_records_with_xg(_records([URL_A]), object(), checkpoint_path=str(checkpoint))

    assert report["xg_fetched_now"] == 1
    assert report["xg_resumed"] == 0
    assert checkpoint.exists()


@pytest.mark.asyncio
async def test_match_without_xg_is_not_cached_and_is_retried(tmp_path, fake_fetch):
    checkpoint = tmp_path / "xg_checkpoint.json"
    unknown = "https://www.chanceliga.cz/zapas/9-x-y"

    records = _records([URL_A, unknown])
    report = await enrich_records_with_xg(records, object(), checkpoint_path=str(checkpoint))

    assert report["xg_enriched"] == 1
    assert set(json.loads(checkpoint.read_text(encoding="utf-8"))) == {URL_A}
    assert records[1].get("home_xg") is None

    fake_fetch.clear()
    await enrich_records_with_xg(_records([URL_A, unknown]), object(), checkpoint_path=str(checkpoint))

    assert fake_fetch == [unknown]
