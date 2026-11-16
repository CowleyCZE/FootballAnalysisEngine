#!/usr/bin/env python3
"""
Scraper pro Chance Ligu.

Primarni zdroj: FotMob (zakladni statistiky)
Fallback pro xG: xgEdge (per-match xG)
"""

import json
import re
import time
import unicodedata

import pandas as pd
import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

LEAGUE_URL = "https://www.fotmob.com/leagues/122/overview/1-liga"
XGEDGE_LEAGUE_URL = "https://xg-edge.com/czech-first-league"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "cs-CZ,cs;q=0.9,en;q=0.8",
}

TOKEN_ALIASES = {
    "prague": "praha",
}


def find_finished_matches(obj, collected, seen_ids):
    if isinstance(obj, dict):
        status = obj.get("status")
        if isinstance(status, dict) and status.get("finished") is True and not status.get("cancelled", False):
            m_id = str(obj.get("id"))
            if m_id and m_id.isdigit() and m_id not in seen_ids:
                seen_ids.add(m_id)
                collected.append(obj)
        for v in obj.values():
            find_finished_matches(v, collected, seen_ids)
    elif isinstance(obj, list):
        for item in obj:
            find_finished_matches(item, collected, seen_ids)


def collect_all_stats(obj, flat_list):
    if isinstance(obj, dict):
        if "title" in obj and "stats" in obj:
            flat_list.append(obj)
        for v in obj.values():
            collect_all_stats(v, flat_list)
    elif isinstance(obj, list):
        for item in obj:
            collect_all_stats(item, flat_list)


def extract_stat(flat_stats, stat_title):
    for item in flat_stats:
        if item.get("title", "").strip().lower() == stat_title.strip().lower():
            vals = item.get("stats", [None, None])
            if isinstance(vals, list) and len(vals) >= 2:
                return vals[0], vals[1]
    return None, None


def slugify(value):
    value = unicodedata.normalize("NFKD", value)
    value = "".join(c for c in value if not unicodedata.combining(c))
    value = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return value


def name_tokens(name):
    slug = slugify(name)
    return [TOKEN_ALIASES.get(token, token) for token in slug.split("-") if token]


def team_matches_slug(team_name, slug):
    team_tokens = set(name_tokens(team_name))
    slug_tokens = set(slugify(slug).split("-"))
    return team_tokens.issubset(slug_tokens)


def fetch_html_requests(url):
    response = requests.get(url, headers=HEADERS, timeout=30)
    response.raise_for_status()
    return response.text


def fetch_html_playwright(url):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=HEADERS["User-Agent"],
            locale="cs-CZ",
        )
        page = context.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(5000)
        html = page.content()
        browser.close()
        return html


def build_xgedge_index():
    """Vytvori index xgEdge zapasu z ligove stranky."""
    try:
        html = fetch_html_requests(XGEDGE_LEAGUE_URL)
    except Exception:
        html = fetch_html_playwright(XGEDGE_LEAGUE_URL)

    soup = BeautifulSoup(html, "html.parser")
    index = []

    for a in soup.find_all("a", href=True):
        href = a["href"]
        match = re.search(
            r"/czech-first-league/([a-z0-9-]+)-vs-([a-z0-9-]+)-(\d{4}-\d{2}-\d{2})",
            href,
        )
        if not match:
            continue

        home_slug, away_slug, date = match.groups()
        if not href.startswith("http"):
            href = f"https://xg-edge.com{href}"

        index.append(
            {
                "url": href,
                "date": date,
                "home_slug": home_slug,
                "away_slug": away_slug,
            }
        )

    return index


def find_xgedge_match(index, home_team, away_team, date):
    for item in index:
        if item["date"] != date:
            continue

        if team_matches_slug(home_team, item["home_slug"]) and team_matches_slug(away_team, item["away_slug"]):
            return item

    return None


def parse_xgedge_xg(html):
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(" ", strip=True)

    patterns = [
        r"xG\s*[:\-–]?\s*([0-9]+(?:\.[0-9]+)?)\s*[-–]\s*([0-9]+(?:\.[0-9]+)?)",
        r"xG[^0-9]{0,40}([0-9]+(?:\.[0-9]+)?)\D{0,40}([0-9]+(?:\.[0-9]+)?)",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            home_xg = float(match.group(1).replace(",", "."))
            away_xg = float(match.group(2).replace(",", "."))
            return home_xg, away_xg

    return None, None


def get_xg_from_xgedge(index, home_team, away_team, date):
    match = find_xgedge_match(index, home_team, away_team, date)
    if not match:
        return None, None

    try:
        html = fetch_html_requests(match["url"])
    except Exception:
        html = fetch_html_playwright(match["url"])

    return parse_xgedge_xg(html)


def run_scraper(max_matches=30):
    records = []
    xgedge_index = None

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=HEADERS["User-Agent"],
            locale="cs-CZ",
        )
        page = context.new_page()

        print(f"Otevírám hlavní stránku ligy: {LEAGUE_URL}")
        page.goto(LEAGUE_URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(3000)

        next_data_el = page.locator("#__NEXT_DATA__")
        finished_matches = []
        seen_ids = set()

        if next_data_el.count() > 0:
            raw_json = json.loads(next_data_el.inner_text())
            find_finished_matches(raw_json, finished_matches, seen_ids)

        print(f"Úspěšně nalezeno {len(finished_matches)} odehraných zápasů ligy.")

        if not finished_matches:
            print("Nepodařilo se najít žádné odehrané zápasy v přehledu.")
            browser.close()
            return pd.DataFrame()

        to_process = finished_matches[:max_matches]
        print(f"Stahuji statistiky pro {len(to_process)} zápasů...\n")

        for idx, match in enumerate(to_process):
            m_id = str(match.get("id"))
            match_url = f"https://www.fotmob.com/match/{m_id}"

            match_data = {}

            def handle_response(response):
                try:
                    if response.status == 200 and "matchDetails" in response.url:
                        match_data["payload"] = response.json()
                except Exception:
                    pass

            page.on("response", handle_response)

            try:
                page.goto(match_url, wait_until="domcontentloaded", timeout=25000)
                page.wait_for_timeout(3000)
            except Exception as e:
                print(f"[{idx + 1}] Chyba při načítání {match_url}: {e}")
                page.remove_listener("response", handle_response)
                continue

            page.remove_listener("response", handle_response)
            payload = match_data.get("payload")

            if not payload:
                try:
                    match_next = page.locator("#__NEXT_DATA__").inner_text()
                    m_json = json.loads(match_next)
                    page_props = m_json.get("props", {}).get("pageProps", {})
                    fallback = page_props.get("fallback", {})
                    for value in fallback.values():
                        if isinstance(value, dict) and "header" in value:
                            payload = value
                            break
                except Exception:
                    pass

            if not payload or not isinstance(payload, dict):
                print(f"[{idx + 1}] Přeskakuji zápas {m_id} (data nejsou dostupná)")
                continue

            header = payload.get("header", {})
            status = header.get("status", {})
            teams = header.get("teams", [{}, {}])

            home_team = teams[0].get("name", match.get("home", {}).get("name", "Domácí"))
            away_team = teams[1].get("name", match.get("away", {}).get("name", "Hosté"))
            home_score = teams[0].get("score", match.get("home", {}).get("score"))
            away_score = teams[1].get("score", match.get("away", {}).get("score"))

            halftime = status.get("halftimeScore")
            ht_home, ht_away = None, None
            if isinstance(halftime, dict):
                ht_home = halftime.get("home")
                ht_away = halftime.get("away")
            elif isinstance(halftime, list) and len(halftime) >= 2:
                ht_home = halftime[0]
                ht_away = halftime[1]

            flat_stats = []
            collect_all_stats(payload.get("content", {}).get("stats", {}), flat_stats)

            home_xg, away_xg = extract_stat(flat_stats, "Expected goals (xG)")
            home_sot, away_sot = extract_stat(flat_stats, "Shots on target")
            home_poss, away_poss = extract_stat(flat_stats, "Ball possession")
            home_rc, away_rc = extract_stat(flat_stats, "Red cards")

            general = payload.get("general", {})
            date_raw = general.get("matchTimeUTCDate") or match.get("status", {}).get("utcTime", "")
            date_clean = date_raw[:10] if date_raw else ""
            time_clean = date_raw[11:16] if date_raw else ""

            if (home_xg is None or away_xg is None) and date_clean:
                if xgedge_index is None:
                    print("Načítám xgEdge index pro fallback xG...")
                    try:
                        xgedge_index = build_xgedge_index()
                        print(f"xgEdge index obsahuje {len(xgedge_index)} zápasů.")
                    except Exception as e:
                        print(f"Chyba při načítání xgEdge indexu: {e}")
                        xgedge_index = []

                if xgedge_index:
                    xg_home, xg_away = get_xg_from_xgedge(
                        xgedge_index,
                        home_team,
                        away_team,
                        date_clean,
                    )

                    if home_xg is None:
                        home_xg = xg_home
                    if away_xg is None:
                        away_xg = xg_away

            records.append(
                {
                    "date": date_clean,
                    "kickoff_time": time_clean,
                    "competition": "Chance Liga",
                    "home_team": home_team,
                    "away_team": away_team,
                    "home_goals": home_score,
                    "away_goals": away_score,
                    "ht_home_goals": ht_home,
                    "ht_away_goals": ht_away,
                    "home_xg": home_xg,
                    "away_xg": away_xg,
                    "home_shots_on_target": home_sot,
                    "away_shots_on_target": away_sot,
                    "home_possession_pct": home_poss,
                    "away_possession_pct": away_poss,
                    "home_red_cards": home_rc or 0,
                    "away_red_cards": away_rc or 0,
                    "status": "Finished",
                }
            )

            print(
                f"[{idx + 1}/{len(to_process)}] OK: {home_team} {home_score}:{away_score} {away_team} | xG: {home_xg} - {away_xg}"
            )
            time.sleep(1.0)

        browser.close()

    df = pd.DataFrame(records)
    csv_file = "czech_league_xg_dataset.csv"
    df.to_csv(csv_file, index=False, encoding="utf-8-sig")
    print(f"\nHotovo! Uloženo {len(df)} dokončených zápasů do '{csv_file}'.")
    return df


if __name__ == "__main__":
    df = run_scraper(max_matches=30)
