#!/usr/bin/env python3
"""
Diagnostika a stahovani xG z alternativnich zdroju pro Chance Ligu.

Podporovane zdroje:
1) Oficialni Chance Liga (chanceliga.cz)
2) FBref (fbref.com) - pres Playwright kvuli 403

Pouziti:
python xg_zdroje.py --chance-url "https://www.chanceliga.cz/..." --fbref-url "https://fbref.com/..." --fbref-url "https://fbref.com/..."
python xg_zdroje.py --discover-chance
"""

import argparse
import csv
import re
from dataclasses import dataclass
from typing import Optional

import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "cs-CZ,cs;q=0.9,en;q=0.8",
}


@dataclass
class XgResult:
    source: str
    url: str
    home_team: Optional[str] = None
    away_team: Optional[str] = None
    home_xg: Optional[float] = None
    away_xg: Optional[float] = None
    found: bool = False
    note: str = ""


def fetch_html_requests(url: str) -> str:
    response = requests.get(url, headers=HEADERS, timeout=30)
    response.raise_for_status()
    return response.text


def fetch_html_playwright(url: str) -> str:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="cs-CZ",
        )
        page = context.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(5000)
        html = page.content()
        browser.close()
        return html


def parse_number(value: str) -> Optional[float]:
    if not value:
        return None

    value = value.replace(",", ".").strip()
    match = re.search(r"\d+(?:\.\d+)?", value)
    return float(match.group()) if match else None


def parse_chance_liga_xg(html: str, url: str) -> XgResult:
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(" ", strip=True)

    patterns = [
        r"xG\s*:?\s*([0-9]+(?:[.,][0-9]+)?)\s*[-–:]\s*([0-9]+(?:[.,][0-9]+)?)",
        r"Očekávané góly\s*\(?xG\)?\s*:?\s*([0-9]+(?:[.,][0-9]+)?)\s*[-–:]\s*([0-9]+(?:[.,][0-9]+)?)",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            home_xg = parse_number(match.group(1))
            away_xg = parse_number(match.group(2))

            if home_xg is not None and away_xg is not None:
                return XgResult(
                    source="Chance Liga",
                    url=url,
                    home_xg=home_xg,
                    away_xg=away_xg,
                    found=True,
                    note="xG nalezeno v textu stranky",
                )

    return XgResult(
        source="Chance Liga",
        url=url,
        found=False,
        note="Per-match xG na strance zapasu nenalezeno",
    )


def parse_fbref_xg(html: str, url: str) -> XgResult:
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(" ", strip=True)

    patterns = [
        r"xG\s*([0-9]+(?:\.[0-9]+)?)\s*[–-]\s*([0-9]+(?:\.[0-9]+)?)",
        r"Expected\s+Goals\s*:?\s*([0-9]+(?:\.[0-9]+)?)\s*[–-]\s*([0-9]+(?:\.[0-9]+)?)",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            home_xg = parse_number(match.group(1))
            away_xg = parse_number(match.group(2))

            if home_xg is not None and away_xg is not None:
                return XgResult(
                    source="FBref",
                    url=url,
                    home_xg=home_xg,
                    away_xg=away_xg,
                    found=True,
                    note="xG nalezeno v match reportu",
                )

    return XgResult(
        source="FBref",
        url=url,
        found=False,
        note="Per-match xG v match reportu nenalezeno",
    )


def discover_chance_liga_matches() -> None:
    url = "https://www.chanceliga.cz/statistiky-landing"
    html = fetch_html_requests(url)
    soup = BeautifulSoup(html, "html.parser")

    links = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        text = a.get_text(" ", strip=True)
        if any(keyword in href.lower() for keyword in ["zapas", "match", "report", "detail"]):
            links.append((text, href))

    print(f"Nalezeno {len(links)} potencialnych odkazu na zapasy.")
    for text, href in links[:30]:
        print(f"- {text} -> {href}")


def save_results(results: list[XgResult], filename: str = "xg_alternativni_zdroje.csv") -> None:
    if not results:
        print("Nejsou k dispozici zadne vysledky k ulozeni.")
        return

    with open(filename, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "source",
                "url",
                "home_team",
                "away_team",
                "home_xg",
                "away_xg",
                "found",
                "note",
            ],
        )
        writer.writeheader()

        for result in results:
            writer.writerow(
                {
                    "source": result.source,
                    "url": result.url,
                    "home_team": result.home_team,
                    "away_team": result.away_team,
                    "home_xg": result.home_xg,
                    "away_xg": result.away_xg,
                    "found": result.found,
                    "note": result.note,
                }
            )

    print(f"Ulozeno {len(results)} vysledku do '{filename}'.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Diagnostika xG z alternativnich zdroju")
    parser.add_argument("--chance-url", help="URL detailu zapasu na chanceliga.cz")
    parser.add_argument("--fbref-url", action="append", help="URL match reportu na fbref.com (lze zadat vicekrat)")
    parser.add_argument("--discover-chance", action="store_true", help="Vyhleda potencialne odkazy na zapasy")
    parser.add_argument("--output", default="xg_alternativni_zdroje.csv", help="Vystupni CSV soubor")

    args = parser.parse_args()

    if args.discover_chance:
        discover_chance_liga_matches()
        return

    results = []

    if args.chance_url:
        try:
            html = fetch_html_requests(args.chance_url)
            result = parse_chance_liga_xg(html, args.chance_url)
            results.append(result)
            print(result)
        except Exception as e:
            print(f"Chyba pri stahovani Chance Liga: {e}")

    if args.fbref_url:
        for url in args.fbref_url:
            try:
                html = fetch_html_playwright(url)
                result = parse_fbref_xg(html, url)
                results.append(result)
                print(result)
            except Exception as e:
                print(f"Chyba pri stahovani FBref pres Playwright: {e}")

    if not results:
        print("Nebyla zadana zadna URL k testovani.")
        print("Pouziti:")
        print("python xg_zdroje.py --chance-url '...' --fbref-url '...' --fbref-url '...'")
        print("python xg_zdroje.py --discover-chance")
        return

    save_results(results, args.output)


if __name__ == "__main__":
    main()
