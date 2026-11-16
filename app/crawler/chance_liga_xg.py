from __future__ import annotations

import re
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup


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


async def fetch_match_xg(match_url: str, client: httpx.AsyncClient) -> tuple[float, float] | None:
    """Stáhne oficiální statistiky zápasu a pokusí se přečíst xG."""
    url = statistics_url(match_url)
    response = await client.get(url)
    if response.status_code != 200:
        return None
    return extract_xg_from_html(response.text)


async def enrich_records_with_xg(
    records: list[dict[str, object]],
    client: httpx.AsyncClient,
) -> dict[str, int]:
    """Doplní xG do záznamů z oficiálních stránek zápasů.

    Záznamy bez odkazu nebo bez čitelných hodnot zůstávají s xG NULL.
    """
    fetched = 0
    enriched = 0

    for record in records:
        match_url = record.get("match_url")
        if not match_url:
            continue

        fetched += 1
        xg = await fetch_match_xg(str(match_url), client)
        if xg is None:
            continue

        record["home_xg"] = xg[0]
        record["away_xg"] = xg[1]
        enriched += 1

    return {"matches_with_url": fetched, "xg_enriched": enriched}


def absolute_url(url: str, base: str = "https://www.chanceliga.cz") -> str:
    return urljoin(base, url)
