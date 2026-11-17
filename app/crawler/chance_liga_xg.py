from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup
from tqdm import tqdm

from app.crawler.chance_liga_history import _fetch_with_playwright


def statistics_url(match_url: str) -> str:
    """Z detailu zápasu vytvoří adresu stránky se statistikami."""
    if "/zapas/statistiky/" in match_url:
        return match_url
    return match_url.replace("/zapas/", "/zapas/statistiky/", 1)


def _number(value: str) -> float | None:
    try:
        return float(value.replace(",", "."))
    except (TypeError, ValueError):
        return None


def extract_xg_from_html(html: str) -> tuple[float, float] | None:
    """Extrahuje dvojici xG domácí / hosté ze stránky statistik zápasu.

    Pokud nelze jednoznačně přečíst obě hodnoty, vrací None. Nevymýšlí ani
    neodhaduje chybějící xG.
    """
    soup = BeautifulSoup(html or "", "html.parser")

    for row in soup.select("tr"):
        text = row.get_text(" ", strip=True)
        if not re.search(r"\bxG\b", text, flags=re.IGNORECASE):
            continue
        if re.search(r"\bxGOT\b", text, flags=re.IGNORECASE):
            continue

        numbers = re.findall(r"\d+(?:[.,]\d+)?", text)
        values = [_number(value) for value in numbers]
        values = [value for value in values if value is not None]
        if len(values) >= 2:
            return values[0], values[1]

    match = re.search(
        r"\bxG\b[^0-9\-]{0,120}(\d+(?:[.,]\d+)?)[^0-9\-]{0,120}(\d+(?:[.,]\d+)?)",
        soup.get_text(" ", strip=True),
        flags=re.IGNORECASE,
    )
    if not match:
        return None

    home_xg = _number(match.group(1))
    away_xg = _number(match.group(2))
    if home_xg is None or away_xg is None:
        return None
    return home_xg, away_xg


async def fetch_match_xg(
    match_url: str,
    client: httpx.AsyncClient,
    max_attempts: int = 4,
) -> tuple[float, float] | None:
    """Stáhne oficiální statistiky zápasu a pokusí se přečíst xG."""
    url = statistics_url(match_url)

    for attempt in range(1, max_attempts + 1):
        try:
            response = await client.get(url)
            response.raise_for_status()
            return extract_xg_from_html(response.text)
        except httpx.HTTPStatusError as error:
            if error.response.status_code not in {403, 429}:
                return None
        except (httpx.TransportError, httpx.RemoteProtocolError):
            if attempt < max_attempts:
                await asyncio.sleep(2 ** attempt)
                continue

    html = await _fetch_with_playwright(url)
    if not html:
        return None
    return extract_xg_from_html(html)


def _load_checkpoint(path: str | None) -> dict[str, list[float]]:
    if not path:
        return {}
    checkpoint = Path(path)
    if not checkpoint.exists():
        return {}
    try:
        data = json.loads(checkpoint.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return {str(key): value for key, value in data.items() if isinstance(value, list) and len(value) == 2}
    except (OSError, json.JSONDecodeError):
        pass
    return {}


def _save_checkpoint(path: str | None, data: dict[str, list[float]]) -> None:
    if not path:
        return
    checkpoint = Path(path)
    checkpoint.parent.mkdir(parents=True, exist_ok=True)
    tmp = checkpoint.with_suffix(checkpoint.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(checkpoint)


async def enrich_records_with_xg(
    records: list[dict[str, object]],
    client: httpx.AsyncClient,
    checkpoint_path: str | None = None,
) -> dict[str, int]:
    """Doplní xG do záznamů z oficiálních stránek zápasů.

    Úspěšně stažené hodnoty se průběžně ukládají do checkpoint souboru,
    takže přerušený import lze bezpečně obnovit bez opakovaného stahování.
    Záznamy bez odkazu nebo bez čitelných hodnot zůstávají s xG NULL.
    """
    checkpoint = _load_checkpoint(checkpoint_path)
    fetched = 0
    enriched = 0
    resumed = 0

    for record in tqdm(records, desc="xG enrichment", unit="match"):
        match_url = record.get("match_url")
        if not match_url:
            continue

        key = str(match_url)
        cached = checkpoint.get(key)
        if cached is not None:
            xg = (float(cached[0]), float(cached[1]))
            resumed += 1
        else:
            fetched += 1
            xg = await fetch_match_xg(key, client)
            if xg is None:
                continue
            checkpoint[key] = [xg[0], xg[1]]
            _save_checkpoint(checkpoint_path, checkpoint)

        record["home_xg"] = xg[0]
        record["away_xg"] = xg[1]
        enriched += 1

    _save_checkpoint(checkpoint_path, checkpoint)
    return {
        "matches_with_url": fetched + resumed,
        "xg_enriched": enriched,
        "xg_resumed": resumed,
        "xg_fetched_now": fetched,
    }


def absolute_url(url: str, base: str = "https://www.chanceliga.cz") -> str:
    return urljoin(base, url)
