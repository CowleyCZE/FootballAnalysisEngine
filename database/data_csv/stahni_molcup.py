"""Download current MOL Cup fixtures and results from the official results page."""
import re
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import requests
from bs4 import BeautifulSoup

PRAGUE_TZ = ZoneInfo("Europe/Prague")
CZECH_CLUBS = [
    "Slavia", "Sparta", "Plzeň", "Plzen", "Ostrava", "Baník", "Banik",
    "Boleslav", "Liberec", "Olomouc", "Sigma", "Jablonec", "Teplice",
    "Bohemians", "Slovácko", "Slovacko", "Hradec", "Pardubice", "Zlín",
    "Zlin", "Zbrojovka", "Artis", "Dukla", "Karviná", "Karvina",
]


def is_czech_match(home, away):
    return any(token.casefold() in f"{home} {away}".casefold() for token in CZECH_CLUBS)


def _date(text):
    match = re.search(r"(\d{1,2})\s*/\s*(\d{1,2})\s*/\s*(\d{4})", text or "")
    if not match:
        return ""
    day, month, year = map(int, match.groups())
    return date(year, month, day).isoformat()


def _team_name(logo):
    anchor = logo.find("a") if logo else None
    image = anchor.find("img") if anchor else None
    return ((image.get("alt") or image.get("title") or "").strip() if image else "") or (anchor.get_text(" ", strip=True) if anchor else "")


def parse_results(html):
    soup = BeautifulSoup(html, "html.parser")
    records = []
    for item in soup.select("div.item"):
        logos = item.select(".game-info-container .logo")
        if len(logos) < 2:
            # Backward-compatible parsing for the former result card markup.
            home_el = item.select_one(".name.right")
            away_el = item.select_one(".name:not(.right)")
            home = home_el.get_text(" ", strip=True) if home_el else ""
            away = away_el.get_text(" ", strip=True) if away_el else ""
        else:
            home, away = _team_name(logos[0]), _team_name(logos[1])
        if not home or not away or not is_czech_match(home, away):
            continue

        day = _date((item.select_one(".date") or item).get_text(" ", strip=True))
        if not day:
            continue
        stage = item.select_one(".stage")
        score = item.select_one(".score")
        score_match = re.search(r"(\d{1,2})\s*[:\-–]\s*(\d{1,2})", score.get_text(" ", strip=True)) if score else None
        hg, ag = (int(score_match.group(1)), int(score_match.group(2))) if score_match else (None, None)
        time_el = item.select_one(".time")
        kickoff = re.search(r"\d{1,2}:\d{2}", time_el.get_text(" ", strip=True)).group(0) if time_el and re.search(r"\d{1,2}:\d{2}", time_el.get_text(" ", strip=True)) else ""
        utc = ""
        if kickoff:
            local = datetime.strptime(f"{day} {kickoff}", "%Y-%m-%d %H:%M").replace(tzinfo=PRAGUE_TZ)
            utc = local.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%d %H:%M UTC")
        records.append({
            "date": day,
            "time_local": kickoff,
            "kickoff_local": f"{day} {kickoff}".strip(),
            "kickoff_utc": utc,
            "competition": "MOL Cup",
            "round": stage.get_text(" ", strip=True) if stage else "MOL Cup",
            "home_team": home,
            "away_team": away,
            "home_goals": hg,
            "away_goals": ag,
            "status": "Finished" if score_match else "Scheduled",
        })
    return records


def main():
    url = "https://www.molcup.cz/vysledky"
    response = requests.get(url, headers={
        "User-Agent": "Mozilla/5.0 (compatible; FootballAnalysisEngine/1.0)",
        "Accept-Language": "cs-CZ,cs;q=0.9",
    }, timeout=30)
    response.raise_for_status()
    records = parse_results(response.content)
    if not records:
        raise RuntimeError("Zdroj MOL Cup nevrátil žádné české klubové zápasy; CSV nebylo vytvořeno.")
    output = Path("mol_cup_dataset.csv")
    pd.DataFrame(records).to_csv(output, index=False, encoding="utf-8-sig")
    finished = sum(row["status"] == "Finished" for row in records)
    print(f"Uloženo {len(records)} zápasů MOL Cupu ({finished} dokončených) do {output}.")


if __name__ == "__main__":
    main()
