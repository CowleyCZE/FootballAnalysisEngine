import re
import time
import pandas as pd
from playwright.sync_api import sync_playwright

BASE_URL = "https://www.chanceliga.cz"
ROZPIS_URL = f"{BASE_URL}/rozpis-zapasu"

def parse_match_page(page, url):
    """Otevře detail zápasu na chanceliga.cz a vytáhne xG a statistiky."""
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(1000)
    except Exception as e:
        print(f"Chyba při načítání {url}: {e}")
        return None

    body_text = page.inner_text("body")
    title_text = page.title()

    # 1. Týmy z titulku stránky (např. 'Detail zápasu FC Zlín - SK Sigma Olomouc | Chance Liga')
    title_match = re.search(r'Detail zápasu\s+(.*?)\s+[\-\–]\s+(.*?)\s+[\|\-]\s+Chance Liga', title_text, re.IGNORECASE)
    if title_match:
        home_team = title_match.group(1).strip()
        away_team = title_match.group(2).strip()
    else:
        return None

    # 2. Skutečné skóre zápasu:
    # U odehraných zápasů je vždy uveden poločas ve formátu '(0:0)' nebo '. (0:0)'
    # Tím se 100% vyhneme záměně s časem výkopu jako 18:00
    score_match = re.search(r'(?:^|\s)(\d{1,2})\s*:\s*(\d{1,2})\s*[\.\s]*\((?:(\d{1,2})\s*:\s*(\d{1,2}))\)', body_text)
    
    if not score_match:
        # Zápas nemá poločasové skóre -> nebyl odehrán nebo je odložen/budoucí
        return None

    home_goals = int(score_match.group(1))
    away_goals = int(score_match.group(2))
    ht_home = int(score_match.group(3))
    ht_away = int(score_match.group(4))

    # Ochrana: pokud by se náhodou chytil nesmysl (např. víc než 15 gólů)
    if home_goals > 15 or away_goals > 15:
        return None

    # 3. Datum a čas (např. 'sobota 24/10/2026, 15:00')
    date_match = re.search(r'(\d{1,2})/(\d{1,2})/(\d{4})(?:[,\s]+(\d{2}:\d{2}))?', body_text)
    match_date = ""
    kickoff_time = ""
    if date_match:
        day, month, year, k_time = date_match.groups()
        match_date = f"{year}-{int(month):02d}-{int(day):02d}"
        kickoff_time = k_time if k_time else ""

    # 4. Očekávané góly (xG) - Opta tabulka: '1.04, xG, 2.02' nebo '1.04 xG 2.02'
    home_xg, away_xg = None, None
    xg_table = re.search(r'(\d+(?:\.\d+)?)\s*(?:,|\n|\s)+xG\s*(?:,|\n|\s)+(\d+(?:\.\d+)?)', body_text, re.IGNORECASE)
    if xg_table:
        home_xg = float(xg_table.group(1))
        away_xg = float(xg_table.group(2))
    else:
        xg_text = re.search(r'Očekávané góly\s*([0-9]+[,\.][0-9]+)\s*:\s*([0-9]+[,\.][0-9]+)', body_text, re.IGNORECASE)
        if xg_text:
            home_xg = float(xg_text.group(1).replace(",", "."))
            away_xg = float(xg_text.group(2).replace(",", "."))

    # 5. Střely na branku - Opta tabulka: '12/6, Střely/na branku, 8/4' (druhé číslo je na branku)
    home_sot, away_sot = None, None
    sot_table = re.search(r'\d+/(\d+)\s*(?:,|\n|\s)+Střely/na branku\s*(?:,|\n|\s)+\d+/(\d+)', body_text, re.IGNORECASE)
    if sot_table:
        home_sot = int(sot_table.group(1))
        away_sot = int(sot_table.group(2))
    else:
        sot_text = re.search(r'Střely na branku\s*(\d+)\s*:\s*(\d+)', body_text, re.IGNORECASE)
        if sot_text:
            home_sot = int(sot_text.group(1))
            away_sot = int(sot_text.group(2))

    # 6. Držení míče - '55%, Držení míče, 45%' nebo 'Držení míče, 55%'
    home_poss, away_poss = None, None
    poss_table = re.search(r'(\d+)\s*%\s*(?:,|\n|\s)+Držení míče\s*(?:,|\n|\s)+(\d+)\s*%', body_text, re.IGNORECASE)
    if poss_table:
        home_poss = int(poss_table.group(1))
        away_poss = int(poss_table.group(2))
    else:
        poss_single = re.search(r'Držení míče\s*,\s*(\d+)\s*%', body_text, re.IGNORECASE)
        if poss_single:
            home_poss = int(poss_single.group(1))
            away_poss = 100 - home_poss

    # 7. Červené karty
    rc_match = re.search(r'Červené karty\s*(\d+)\s*:\s*(\d+)', body_text, re.IGNORECASE)
    home_rc = int(rc_match.group(1)) if rc_match else 0
    away_rc = int(rc_match.group(2)) if rc_match else 0

    return {
        "date": match_date,
        "kickoff_time": kickoff_time,
        "competition": "Chance Liga",
        "home_team": home_team,
        "away_team": away_team,
        "home_goals": home_goals,
        "away_goals": away_goals,
        "ht_home_goals": ht_home,
        "ht_away_goals": ht_away,
        "home_xg": home_xg,
        "away_xg": away_xg,
        "home_shots_on_target": home_sot,
        "away_shots_on_target": away_sot,
        "home_possession_pct": home_poss,
        "away_possession_pct": away_poss,
        "home_red_cards": home_rc,
        "away_red_cards": away_rc,
        "status": "Finished"
    }

def run_scraper(target_matches=50):
    records = []
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            locale="cs-CZ"
        )
        page = context.new_page()

        print(f"Otevírám oficiální rozpis: {ROZPIS_URL}")
        page.goto(ROZPIS_URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(2000)

        # Najdeme všechny unikátní odkazy na zápasy
        hrefs = page.eval_on_selector_all(
            "a[href*='/zapas/']", 
            "elements => elements.map(e => e.getAttribute('href'))"
        )

        match_urls = []
        for h in hrefs:
            if not h:
                continue
            clean_h = h.split("#")[0]
            full_url = clean_h if clean_h.startswith("http") else f"{BASE_URL}{clean_h}"
            if full_url not in match_urls:
                match_urls.append(full_url)

        print(f"Nalezeno {len(match_urls)} odkazů v rozpisu ligy. Hledám dokončené zápasy (cíl: {target_matches})...\n")

        for url in match_urls:
            if len(records) >= target_matches:
                break

            match_row = parse_match_page(page, url)
            
            if match_row and match_row.get("home_goals") is not None:
                records.append(match_row)
                poss_str = f"{match_row['home_possession_pct']}%:{match_row['away_possession_pct']}%" if match_row['home_possession_pct'] else "N/A"
                print(f"[{len(records)}/{target_matches}] ✓ {match_row['date']} {match_row['kickoff_time']} | {match_row['home_team']} {match_row['home_goals']}:{match_row['away_goals']} {match_row['away_team']} (poločas {match_row['ht_home_goals']}:{match_row['ht_away_goals']}) | xG: {match_row['home_xg']} - {match_row['away_xg']} | Držení: {poss_str}")
            else:
                # Neodehrané / budoucí zápasy se tiše přeskočí
                pass

            time.sleep(0.8)

        browser.close()

    df = pd.DataFrame(records)
    csv_file = "czech_league_xg_dataset.csv"
    df.to_csv(csv_file, index=False, encoding="utf-8-sig")
    print(f"\nHotovo! Uloženo {len(df)} skutečně odehraných zápasů do '{csv_file}'.")
    return df

if __name__ == "__main__":
    # Nastavte požadovaný počet odehraných zápasů (např. 50 nebo 100)
    df = run_scraper(target_matches=240)
    print("\nUkázka výsledných dat:")
    print(df[["date", "home_team", "away_team", "home_goals", "away_goals", "ht_home_goals", "ht_away_goals", "home_xg", "away_xg"]].head())
