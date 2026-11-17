from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from app.crawler.chance_liga_xg import enrich_records_with_xg


def _records(urls):
    return [{"match_url": url} for url in urls]


@pytest.mark.asyncio
async def test_resume_uses_checkpoint_and_skips_refetch(tmp_path):
    checkpoint = tmp_path / "xg_checkpoint.json"
    records = _records([
        "https://www.chanceliga.cz/zapas/1-a-b",
        "https://www.chanceliga.cz/zapas/2-c-d",
    ])

    async with httpx.AsyncClient() as client:
        report = await enrich_records_with_xg(records, client, checkpoint_path=str(checkpoint))

    assert report["xg_fetched_now"] == 2
    assert report["xg_resumed"] == 0
    assert checkpoint.exists()

    saved = json.loads(checkpoint.read_text(encoding="utf-8"))
    assert len(saved) == 2

    records2 = _records([
        "https://www.chanceliga.cz/zapas/1-a-b",
        "https://www.chanceliga.cz/zapas/2-c-d",
    ])
    async with httpx.AsyncClient() as client:
        report2 = await enrich_records_with_xg(records2, client, checkpoint_path=str(checkpoint))

    assert report2["xg_resumed"] == 2
    assert report2["xg_fetched_now"] == 0


@pytest.mark.asyncio
async def test_resume_after_partial_run(tmp_path):
    checkpoint = tmp_path / "xg_checkpoint.json"
    all_urls = [
        "https://www.chanceliga.cz/zapas/1-a-b",
        "https://www.chanceliga.cz/zapas/2-c-d",
        "https://www.chanceliga.cz/zapas/3-e-f",
    ]

    # První běh: zpracujeme jen první dva zápasy.
    records = _records(all_urls[:2])
    async with httpx.AsyncClient() as client:
        report = await enrich_records_with_xg(records, client, checkpoint_path=str(checkpoint))
    assert report["xg_fetched_now"] == 2

    # Druhý běh: přidáme třetí zápas, první dva se obnoví z checkpointu.
    records2 = _records(all_urls)
    async with httpx.AsyncClient() as client:
        report2 = await enrich_records_with_xg(records2, client, checkpoint_path=str(checkpoint))

    assert report2["xg_resumed"] == 2
    assert report2["xg_fetched_now"] == 1
    assert report2["xg_enriched"] == 3


@pytest.mark.asyncio
async def test_corrupted_checkpoint_starts_fresh(tmp_path):
    checkpoint = tmp_path / "xg_checkpoint.json"
    checkpoint.write_text("{not valid json", encoding="utf-8")

    records = _records(["https://www.chanceliga.cz/zapas/1-a-b"])
    async with httpx.AsyncClient() as client:
        report = await enrich_records_with_xg(records, client, checkpoint_path=str(checkpoint))

    assert report["xg_fetched_now"] == 1
    assert report["xg_resumed"] == 0
    # Po úspěšném stažení se checkpoint přepíše platným JSON.
    saved = json.loads(checkpoint.read_text(encoding="utf-8"))
    assert len(saved) == 1


@pytest.mark.asyncio
async def test_missing_checkpoint_file_behaves_as_empty(tmp_path):
    checkpoint = tmp_path / "xg_checkpoint.json"

    records = _records(["https://www.chanceliga.cz/zapas/1-a-b"])
    async with httpx.AsyncClient() as client:
        report = await enrich_records_with_xg(records, client, checkpoint_path=str(checkpoint))

    assert report["xg_fetched_now"] == 1
    assert report["xg_resumed"] == 0
    assert checkpoint.exists()
