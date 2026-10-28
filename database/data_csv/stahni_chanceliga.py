import re
import time
from datetime import datetime
from zoneinfo import ZoneInfo
import pandas as pd
from playwright.sync_api import sync_playwright

PRAGUE_TZ = ZoneInfo("Europe/Prague")
BASE_URL = "https://www.chanceliga.cz"
ROZPIS_URL = f"{BASE_URL}/rozpis-zapasu"

def parse_match(page, url):
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=25000)
        page.wait_for_timeout(400)
    except Exception:
        return None

    body = page.inner_text("body")
    title = page.title()

    # Týmy z titulku
    t_match = re.search(r'Detail zápasu\s+(.*?)\s+[\-\–]\s+(.*?)\s+[\|\-]', title)
    if not t_match:
        return None
    home, away = t_match.group(1).strip(), t_match.group(2).strip()

    # Datum a čas
    d_match = re.search(r'(\d{1,2})/(\d{1,2})/(\d{4})(?:[,\s]+(\d{2}:\d{2}))?', body)
    date_str, time_str, utc_str = "", "", ""
    if d_match:
        d, mo, y, t = d_match.groups()
        date_str = f"{y}-{int(mo):02d}-{int(d):02d}"
        time_str = t or ""
        if time_str:
            try:
                dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M").replace(tzinfo=PRAGUE_TZ)
                utc_str = dt.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%d %H:%M UTC")
            except Exception:
                pass

    # Kolo
    r_match = re.search(r'(\d+\.\s*kolo)', body)
    round_name = r_match.group(1) if r_match else ""

    # Skóre a poločas
    score_match = re.search(r'(?:^|\s)(\d{1,2})\s*:\s*(\d{1,2})\s*[\.\s]*\((?:(\d{1,2})\s*:\s*(\d{1,2}))\)', body)
    if score_match:
        hg, ag = int(score_match.group(1)), int(score_match.group(2))
        ht_h, ht_a = int(score_match.group(3)), int(score_match.group(4))
        status = "Finished"
    else:
        hg, ag, ht_h, ht_a = None, None, None, None
        status = "Scheduled"

    # xG (Opta)
    home_xg, away_xg = None, None
    if status == "Finished":
        xg_t = re.search(r'(\d+(?:\.\d+)?)\s*(?:,|\n|\s)+xG\s*(?:,|\n|\s)+(\d+(?:\.\d+)?)', body, re.IGNORECASE)
        if xg_t:
            home_xg, away_xg = float(xg_t.group(1)), float(xg_t.group(2))

    # Střely na branku
    home_sot, away_sot = None, None
    if status == "Finished":
        sot_t = re.search(r'\d+/(\d+)\s*(?:,|\n|\s)+Střely/na branku\s*(?:,|\n|\s)+\d+/(\d+)', body, re.IGNORECASE)
        if sot_t:
            home_sot, away_sot = int(sot_t.group(1)), int(sot_t.group(2))

    # Držení míče
    home_poss, away_poss = None, None
    if status == "Finished":
        poss_t = re.search(r'(\d+)\s*%\s*(?:,|\n|\s)+Držení míče\s*(?:,|\n|\s)+(\d+)\s*%', body, re.IGNORECASE)
        if poss_t:
            home_poss, away_poss = int(poss_t.group(1)), int(poss_t.group(2))
        else:
            poss_s = re.search(r'Držení míče\s*,\s*(\d+)\s*%', body, re.IGNORECASE)
            if poss_s:
                home_poss = int(poss_s.group(1))
                away_poss = 100 - home_poss

    # Červené karty
    rc_m = re.search(r'Červené karty\s*(\d+)\s*:\s*(\d+)', body, re.IGNORECASE)
    home_rc = int(rc_m.group(1)) if rc_m else 0
    away_rc = int(rc_m.group(2)) if rc_m else 0

    return {
        "date": date_str,
        "time_local": time_str,
        "kickoff_local": f"{date_str} {time_str}".strip(),
        "kickoff_utc": utc_str,
        "competition": "Chance Liga",
        "round": round_name,
        "home_team": home,
        "away_team": away,
        "home_goals": hg,
        "away_goals": ag,
        "ht_home_goals": ht_h,
        "ht_away_goals": ht_a,
        "home_xg": home_xg,
        "away_xg": away_xg,
        "home_shots_on_target": home_sot,
        "away_shots_on_target": away_sot,
        "home_possession_pct": home_poss,
        "away_possession_pct": away_poss,
        "home_red_cards": home_rc,
        "away_red_cards": away_rc,
        "status": status
    }

def main():
    print("Spouštím stahování Chance Ligy...")
    records = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(ROZPIS_URL, wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(2000)

        hrefs = page.eval_on_selector_all("a[href*='/zapas/']", "elements => elements.map(e => e.getAttribute('href'))")
        urls = []
        seen = set()
        for h in hrefs:
            clean = h.split("#")[0]
            m = re.search(r'/zapas/(\d+)', clean)
            if m and m.group(1) not in seen:
                seen.add(m.group(1))
                urls.append(f"{BASE_URL}{clean}")

        print(f"Nalezeno {len(urls)} zápasů. Stahuji detaily...")
        for idx, u in enumerate(urls):
            row = parse_match(page, u)
            if row:
                records.append(row)
                if row["status"] == "Finished":
                    print(f"[{idx+1}/{len(urls)}] ✓ {row['date']} | {row['home_team']} {row['home_goals']}:{row['away_goals']} {row['away_team']} | xG: {row['home_xg']}-{row['away_xg']}")
                else:
                    print(f"[{idx+1}/{len(urls)}] 📅 {row['date']} {row['time_local']} | {row['home_team']} vs {row['away_team']} (Plánováno)")
            time.sleep(0.3)

        browser.close()

    df = pd.DataFrame(records)
    df.to_csv("chance_liga_dataset.csv", index=False, encoding="utf-8-sig")
    print(f"\nHotovo! Uloženo {len(df)} ligových zápasů do 'chance_liga_dataset.csv'.")

if __name__ == "__main__":
    main()
