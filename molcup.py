import re
from datetime import datetime
from zoneinfo import ZoneInfo
import pandas as pd
from playwright.sync_api import sync_playwright

PRAGUE_TZ = ZoneInfo("Europe/Prague")

CZECH_CLUBS = [
    "Slavia", "Sparta", "Plzeň", "Plzen", "Ostrava", "Baník", "Banik",
    "Boleslav", "Liberec", "Olomouc", "Sigma", "Jablonec", "Teplice",
    "Bohemians", "Slovácko", "Slovacko", "Hradec", "Pardubice",
    "Zlín", "Zlin", "Zbrojovka", "Artis", "Dukla", "Karviná", "Karvina"
]

def is_czech_match(home, away):
    h, a = home.lower(), away.lower()
    return any(c.lower() in h or c.lower() in a for c in CZECH_CLUBS)

def scrape_molcup():
    records = []
    seen = set()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            locale="cs-CZ"
        )
        page = context.new_page()

        url = "https://www.molcup.cz/vysledky"
        print(f"Otevírám {url}...")
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(2000)

        # Extrahujeme zápasy přesně podle poskytnutého HTML
        raw_items = page.evaluate("""
            () => {
                const items = document.querySelectorAll('div.item');
                const list = [];
                items.forEach(el => {
                    // Týmy
                    const homeEl = el.querySelector('div.name.right .shortcut a');
                    const awayEl = el.querySelector('div.name:not(.right) .shortcut a');
                    
                    if (!homeEl || !awayEl) return;
                    
                    const home = homeEl.innerText.trim();
                    const away = awayEl.innerText.trim();
                    
                    // Kolo
                    const stageEl = el.querySelector('div.stage');
                    const stage = stageEl ? stageEl.innerText.trim() : '';

                    // 1. Varianta pro odehrané (Výsledky)
                    const dtEl = el.querySelector('div.datetime');
                    const scoreEl = el.querySelector('div.score');

                    // 2. Varianta pro budoucí (Rozpis)
                    const dateLongEl = el.querySelector('div.date div.long');
                    const timeShortEl = el.querySelector('div.time div.short');

                    list.push({
                        home: home,
                        away: away,
                        stage: stage,
                        datetime_raw: dtEl ? dtEl.innerText.trim() : '',
                        score_raw: scoreEl ? scoreEl.innerText.trim() : '',
                        date_future: dateLongEl ? dateLongEl.innerText.trim() : '',
                        time_future: timeShortEl ? timeShortEl.innerText.trim() : ''
                    });
                });
                return list;
            }
        """)

        print(f"Nalezeno {len(raw_items)} karet na stránce. Zpracovávám...")

        for m in raw_items:
            home = m["home"]
            away = m["away"]

            # Filtrujeme pouze zápasy s účastí 1. ligy
            if not is_czech_match(home, away):
                continue

            date_str = ""
            time_str = ""
            hg, ag = None, None
            status = "Scheduled"

            # Zpracování odehraného zápasu (Výsledky)
            if m["datetime_raw"]:
                # Formát: "02.10.2026 - 18:00"
                d_match = re.search(r'(\d{1,2})\.(\d{1,2})\.(\d{4})(?:\s*-\s*(\d{2}:\d{2}))?', m["datetime_raw"])
                if d_match:
                    d, mo, y, t = d_match.groups()
                    date_str = f"{y}-{int(mo):02d}-{int(d):02d}"
                    time_str = t or ""

                if m["score_raw"]:
                    sc_match = re.search(r'(\d{1,2})\s*:\s*(\d{1,2})', m["score_raw"])
                    if sc_match:
                        hg = int(sc_match.group(1))
                        ag = int(sc_match.group(2))
                        status = "Finished"

            # Zpracování budoucího zápasu (Rozpis)
            elif m["date_future"]:
                # Formát: "28/10/2026"
                parts = m["date_future"].replace(" ", "").split("/")
                if len(parts) == 3:
                    date_str = f"{parts[2]}-{int(parts[1]):02d}-{int(parts[0]):02d}"
                time_str = m["time_future"] or ""
                status = "Scheduled"

            if not date_str:
                continue

            key = f"{date_str}_{home}_{away}"
            if key in seen:
                continue
            seen.add(key)

            # UTC výpočet
            utc_str = ""
            if date_str and time_str:
                try:
                    dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M").replace(tzinfo=PRAGUE_TZ)
                    utc_str = dt.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%d %H:%M UTC")
                except Exception:
                    pass

            records.append({
                "match_id": f"MOL_{date_str}_{home[:3]}_{away[:3]}",
                "date": date_str,
                "time_local": time_str,
                "kickoff_local": f"{date_str} {time_str}".strip(),
                "kickoff_utc": utc_str,
                "competition": "MOL Cup",
                "round": m["stage"],
                "home_team": home,
                "away_team": away,
                "home_goals": hg,
                "away_goals": ag,
                "status": status
            })
            
            res_info = f"{hg}:{ag}" if hg is not None else "Plánováno"
            print(f"   ✓ {date_str} {time_str} | {home} vs {away} ({m['stage']}) -> {res_info}")

        browser.close()

    df = pd.DataFrame(records)
    print(f"\nHotovo! Úspěšně staženo {len(df)} pohárových zápasů.")
    if not df.empty:
        df.to_csv("molcup_vysledek.csv", index=False, encoding="utf-8-sig")
    return df

if __name__ == "__main__":
    scrape_molcup()
