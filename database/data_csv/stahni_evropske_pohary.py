import json
from datetime import datetime
from zoneinfo import ZoneInfo
import pandas as pd
from playwright.sync_api import sync_playwright

PRAGUE_TZ = ZoneInfo("Europe/Prague")

CZECH_CLUBS = ["Slavia", "Sparta", "Plzeň", "Plzen", "Boleslav", "Jablonec", "Baník", "Banik"]

def is_czech_match(home, away):
    h, a = home.lower(), away.lower()
    return any(c.lower() in h or c.lower() in a for c in CZECH_CLUBS)

def main():
    print("Spouštím stahování evropských pohárů (UEFA)...")
    uefa_leagues = [
        ("UEFA Champions League", "https://www.fotmob.com/leagues/42/overview/champions-league"),
        ("UEFA Europa League", "https://www.fotmob.com/leagues/73/overview/europa-league"),
        ("UEFA Conference League", "https://www.fotmob.com/leagues/10216/overview/conference-league")
    ]

    records = []
    seen = set()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        for comp_name, url in uefa_leagues:
            print(f"Načítám {comp_name}...")
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=40000)
                page.wait_for_timeout(2000)

                next_el = page.locator("#__NEXT_DATA__")
                if next_el.count() == 0:
                    continue

                raw_json = json.loads(next_el.inner_text())

                all_m = []
                def extract_m(obj):
                    if isinstance(obj, dict):
                        if "home" in obj and "away" in obj and "status" in obj and "id" in obj:
                            all_m.append(obj)
                        for v in obj.values():
                            extract_m(v)
                    elif isinstance(obj, list):
                        for it in obj:
                            extract_m(it)
                extract_m(raw_json)

                for m in all_m:
                    m_id = str(m.get("id"))
                    if m_id in seen:
                        continue

                    home = m.get("home", {}).get("name", "")
                    away = m.get("away", {}).get("name", "")

                    if not is_czech_match(home, away):
                        continue

                    seen.add(m_id)
                    hg = m.get("home", {}).get("score")
                    ag = m.get("away", {}).get("score")
                    st = m.get("status", {})
                    finished = st.get("finished", False)
                    utc_time = st.get("utcTime", "")

                    date_str, time_str, utc_str, loc_str = "", "", "", ""
                    if utc_time:
                        try:
                            clean_ts = utc_time.replace("Z", "+00:00")
                            dt_obj = datetime.fromisoformat(clean_ts)
                            dt_loc = dt_obj.astimezone(PRAGUE_TZ)
                            utc_str = dt_obj.strftime("%Y-%m-%d %H:%M UTC")
                            loc_str = dt_loc.strftime("%Y-%m-%d %H:%M")
                            date_str = dt_loc.strftime("%Y-%m-%d")
                            time_str = dt_loc.strftime("%H:%M")
                        except Exception:
                            date_str = utc_time[:10]

                    records.append({
                        "date": date_str,
                        "time_local": time_str,
                        "kickoff_local": loc_str or date_str,
                        "kickoff_utc": utc_str,
                        "competition": comp_name,
                        "round": m.get("round", "Základní fáze"),
                        "home_team": home,
                        "away_team": away,
                        "home_goals": hg,
                        "away_goals": ag,
                        "status": "Finished" if finished else "Scheduled"
                    })
                    print(f"   ✓ {date_str} {time_str} | {home} vs {away} ({comp_name}) -> {'Odehráno' if finished else 'Plánováno'}")
            except Exception as e:
                print(f"   Chyba: {e}")

        browser.close()

    df = pd.DataFrame(records)
    df.to_csv("evropske_pohary_dataset.csv", index=False, encoding="utf-8-sig")
    print(f"\nHotovo! Uloženo {len(df)} zápasů českých klubů v Evropě do 'evropske_pohary_dataset.csv'.")

if __name__ == "__main__":
    main()
