from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import datetime
from urllib.parse import urljoin, urlparse
from zoneinfo import ZoneInfo

import httpx
from bs4 import BeautifulSoup

try:
    from playwright.async_api import async_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False

PRAGUE_TZ = ZoneInfo("Europe/Prague")
BASE_URL = "https://www.chanceliga.cz"
SCHEDULE_PATH = "/rozpis-zapasu/{year}?type=2"
BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "cs-CZ,cs;q=0.9,en;q=0.8",
    "Referer": "https://www.chanceliga.cz/",
}


def schedule_url(year: int) -> str:
    return BASE_URL + SCHEDULE_PATH.format(year=year)


def season_label(year: int) -> str:
    return f"{year}/{year + 1}"


def _external_match_id(season: str, date: str, home: str, away: str) -> str:
    payload = f"chanceliga:{season}:{date}:{home}:{away}"
    digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()[:24]
    return f"CLH_{digest}"


def _parse_czech_date(value: str) -> str | None:
    match = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", value)
    if not match:
        return None
    day, month, year = (int(part) for part in match.groups())
    try:
        return datetime(year, month, day, tzinfo=PRAGUE_TZ).date().isoformat()
    except ValueError:
        return None


def _slugify(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_text = "".join(char for char in normalized if not unicodedata.combining(char))
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")
    return slug


def _make_record(
    season: str,
    date: str,
    home: str,
    away: str,
    score: str,
    round_name: str,
    match_url: str | None,
) -> dict[str, object]:
    score_match = re.search(r"(\d+)\s*:\s*(\d+)", score)
    if score_match:
        home_goals = int(score_match.group(1))
        away_goals = int(score_match.group(2))
        status = "FINISHED"
    else:
        home_goals = None
        away_goals = None
        status = "SCHEDULED"

    return {
        "external_match_id": _external_match_id(season, date, home, away),
        "competition": "Chance Liga",
        "season": season,
        "home_team": home,
        "away_team": away,
        "scheduled_at": f"{date}T00:00:00+01:00",
        "kickoff_time_known": 0,
        "status": status,
        "round": round_name,
        "home_goals": home_goals,
        "away_goals": away_goals,
        "home_xg": None,
        "away_xg": None,
        "home_xga": None,
        "away_xga": None,
        "match_url": match_url,
    }


def _parse_schedule_table(soup: BeautifulSoup, season: str) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    current_round = ""

    for row in soup.select("tr"):
        cells = [cell.get_text(" ", strip=True) for cell in row.find_all(["td", "th"])]
        if not cells:
            continue

        round_match = re.fullmatch(r"(\d+)\.\s*kolo", cells[0])
        if round_match and len(cells) == 1:
            current_round = round_match.group(1)
            continue

        if len(cells) < 4:
            continue

        date = _parse_czech_date(cells[0])
        home = cells[1]
        score_cell = cells[2]
        away = cells[3]
        if not date or not home or not away:
            continue

        if not re.search(r"(\d+\s*:\s*\d+|-:-)", score_cell):
            continue

        anchor = row.select_one("a[href*='/zapas/']")
        match_url = urljoin(BASE_URL, anchor["href"]) if anchor and anchor.get("href") else None
        records.append(_make_record(season, date, home, away, score_cell, current_round, match_url))

    return records


def _parse_schedule_text(soup: BeautifulSoup, season: str) -> list[dict[str, object]]:
    """Záložní parser pro stránky, které nevystavují zápasy jako klasickou tabulku."""
    lines = [re.sub(r"\s+", " ", line).strip() for line in soup.get_text("\n", strip=True).splitlines()]
    lines = [line for line in lines if line]

    records: list[dict[str, object]] = []
    current_round = ""
    index = 0

    while index < len(lines):
        line = lines[index]

        round_match = re.fullmatch(r"(\d+)\.\s*kolo", line)
        if round_match:
            current_round = round_match.group(1)
            index += 1
            continue

        date = _parse_czech_date(line)
        if not date or index + 3 >= len(lines):
            index += 1
            continue

        home = lines[index + 1]
        score = lines[index + 2]
        away = lines[index + 3]

        if re.fullmatch(r"(\d+\s*:\s*\d+|-:-)", score):
            records.append(_make_record(season, date, home, away, score, current_round, None))
            index += 4
        else:
            index += 1

    return records


def _associate_match_links_by_slug(records: list[dict[str, object]], soup: BeautifulSoup) -> int:
    """Přiřadí URL detailu zápasu podle názvů týmů v URL slugu."""
    candidate_urls: list[str] = []

    for anchor in soup.select("a[href*='/zapas/']"):
        href = anchor.get("href")
        if not href or not re.search(r"/zapas/\d+-", href):
            continue
        candidate_urls.append(urljoin(BASE_URL, href))

    candidate_urls = list(dict.fromkeys(candidate_urls))

    assigned = 0
    for record in records:
        if record.get("match_url"):
            continue

        home_slug = _slugify(str(record["home_team"]))
        away_slug = _slugify(str(record["away_team"]))
        if not home_slug or not away_slug:
            continue

        matches = [
            url
            for url in candidate_urls
            if home_slug in urlparse(url).path
            and away_slug in urlparse(url).path
        ]

        if len(matches) == 1:
            record["match_url"] = matches[0]
            assigned += 1

    return assigned


def parse_schedule_html(html: str, season: str) -> list[dict[str, object]]:
    """Parsuje rozpis Chance Ligy; nejprve tabulku, poté textový fallback."""
    soup = BeautifulSoup(html or "", "html.parser")
    records = _parse_schedule_table(soup, season)
    if not records:
        records = _parse_schedule_text(soup, season)

    _associate_match_links_by_slug(records, soup)
    return records


def diagnose_schedule_html(html: str) -> dict[str, int]:
    """Vrátí diagnostiku struktury stažené stránky."""
    soup = BeautifulSoup(html or "", "html.parser")
    match_links = [
        anchor
        for anchor in soup.select("a[href*='/zapas/']")
        if re.search(r"/zapas/\d+-", anchor.get("href", ""))
    ]

    return {
        "table_rows": len(soup.select("tr")),
        "match_links": len(match_links),
        "text_lines": len([line for line in soup.get_text("\n", strip=True).splitlines() if line.strip()]),
    }


async def _fetch_with_playwright(url: str) -> str | None:
    if not PLAYWRIGHT_AVAILABLE:
        return None

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        try:
            context = await browser.new_context(
                user_agent=BROWSER_HEADERS["User-Agent"],
                locale="cs-CZ",
            )
            page = await context.new_page()
            await page.goto(url, wait_until="domcontentloaded", timeout=45000)
            await page.wait_for_timeout(2000)
            return await page.content()
        finally:
            await browser.close()


async def fetch_season_schedule(year: int, client: httpx.AsyncClient | None = None) -> tuple[str, str]:
    """Stáhne HTML rozpisu; při blokaci HTTP klienta použije Playwright fallback."""
    season = season_label(year)
    url = schedule_url(year)

    try:
        if client is None:
            async with httpx.AsyncClient(
                follow_redirects=True,
                timeout=30,
                headers=BROWSER_HEADERS,
            ) as own_client:
                response = await own_client.get(url)
        else:
            response = await client.get(url, headers=BROWSER_HEADERS)
        response.raise_for_status()
        return season, response.text
    except httpx.HTTPStatusError as error:
        if error.response.status_code not in {403, 429}:
            raise

    html = await _fetch_with_playwright(url)
    if not html:
        raise RuntimeError(
            f"Chance Liga blocked HTTP request ({error.response.status_code}) and Playwright fallback is unavailable. "
            "Install Playwright and Chromium: pip install playwright && playwright install chromium"
        )

    return season, html
