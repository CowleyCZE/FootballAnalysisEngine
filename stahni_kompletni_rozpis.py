import re
import json
import time
from datetime import datetime
from zoneinfo import ZoneInfo
import pandas as pd
from playwright.sync_api import sync_playwright

PRAGUE_TZ = ZoneInfo("Europe/Prague")

# České prvoligové kluby pro filtraci
CZECH_CLUBS = [
    "Slavia", "Sparta", "Plzeň", "Plzen", "Ostrava", "Baník", "Banik",
    "Boleslav", "Liberec", "Olomouc", "Sigma", "Jablonec", "Teplice",
    "Bohemians", "Slovácko", "Slovacko", "Hradec", "Pardubice",
    "Zlín", "Zlin", "Zbrojovka", "Artis"
]

def is_czech_match(home, away):
    """Zkontroluje, zda v zápase hraje český prvoligový tým."""
    h, a = home.lower(), away.lower()
    return any(c.lower() in h or c.lower() in a for c in CZECH_CLUBS)

# ==========================================
# 1. CHANCE LIGA (chanceliga.cz)
# ==========================================
def scrape_chance_liga(page):
    print("1/3 Načítám kompletní Chance Ligu (chanceliga.cz)...")
    url = "https://www.chanceliga.cz/rozpis-zapasu"
    page.goto(url, wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(2000)

    hrefs = page.eval_on_selector_all(
        "a[href*='/zapas/']", 
        "elements => elements.map(e => e.getAttribute('href'))"
    )

    match_urls = []
    seen = set()
    for h in hrefs:
        clean = h.split("#")[0]
        m = re.search(r'/zapas/(\d+)', clean)
        if m and m.group(1) not in seen:
            seen.add(m.group(1))
            match_urls.append((m.group(1), f"https://www.chanceliga.cz{clean}"))

    records = []
    for m_id, m_url in match_urls:
        try:
            page.goto(m_url, wait_until="domcontentloaded", timeout=20000)
            page.wait_for_timeout(400)
            body = page.inner_text("body")
            title = page.title()

            t_match = re.search(r'Detail zápasu\s+(.*?)\s+[\-\–]\s+(.*?)\s+[\|\-]', title)
            if not t_match:
                continue
            home, away = t_match.group(1).strip(), t_match.group(2).strip()

            d_match = re.search(r'(\d{1,2})/(\d{1,2})/(\d{4})(?:[,\s]+(\d{2}:\d{2}))?', body)
            date_str, time_str = "", ""
            if d_match:
                d, mo, y, t = d_match.groups()
                date_str = f"{y}-{int(mo):02d}-{int(d):02d}"
                time_str = t or ""

            r_match = re.search(r'(\d+\.\s*kolo)', body)
            round_name = r_match.group(1) if r_match else ""

            s_match = re.search(r'(?:^|\s)(\d{1,2})\s*:\s*(\d{1,2})\s*[\.\s]*\((?:(\d{1,2})\s*:\s*(\d{1,2}))\)', body)
            if s_match:
                hg, ag = int(s_match.group(1)), int(s_match.group(2))
                status = "Finished"
            else:
                hg, ag = None, None
                status = "Scheduled"

            utc_str = ""
            if date_str and time_str:
                try:
                    dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M").replace(tzinfo=PRAGUE_TZ)
                    utc_str = dt.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%d %H:%M UTC")
                except Exception:
                    pass

            records.append({
                "match_id": f"CL_{m_id}",
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
                "status": status
            })
        except Exception:
            continue

    print(f"   ✓ Načteno {len(records)} zápasů Chance Ligy.")
    return records

# ==========================================
# 2. MOL CUP (Oficiální web molcup.cz)
# ==========================================
def scrape_mol_cup(page):
    print("2/3 Načítám rozpis MOL Cupu (molcup.cz/zapasy-vysledky)...")
    url = "https://www.molcup.cz/zapasy-vysledky"
    records = []
    seen = set()

    try:
        page.goto(url, wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(2000)

        # 1. Posbíráme všechny odkazy na zápasy z aktuálního přehledu
        hrefs = page.eval_on_selector_all(
            "a[href*='/zapas/']", 
            "elements => elements.map(e => e.getAttribute('href'))"
        )

        match_urls = []
        for h in hrefs:
            if not h:
                continue
            clean_h = h.split("#")[0]
            m = re.search(r'/zapas/(\d+)', clean_h)
            if m:
                m_id = m.group(1)
                if m_id not in seen:
                    seen.add(m_id)
                    full_url = clean_h if clean_h.startswith("http") else f"https://www.molcup.cz{clean_h}"
                    match_urls.append((m_id, full_url))

        # 2. Pokud je na stránce výběr kol (filtr), projdeme i ostatní kola (2. kolo, 3. kolo, osmifinále)
        round_options = page.eval_on_selector_all(
            "select[name*='kolo'] option, select[name*='round'] option",
            "elements => elements.map(e => e.value)"
        )
        for r_val in round_options:
            if not r_val or r_val == "0":
                continue
            try:
                page.goto(f"{url}?kolo={r_val}", wait_until="domcontentloaded", timeout=20000)
                page.wait_for_timeout(1000)
                sub_hrefs = page.eval_on_selector_all(
                    "a[href*='/zapas/']", 
                    "elements => elements.map(e => e.getAttribute('href'))"
                )
                for h in sub_hrefs:
                    if not h:
                        continue
                    clean_h = h.split("#")[0]
                    m = re.search(r'/zapas/(\d+)', clean_h)
                    if m and m.group(1) not in seen:
                        seen.add(m.group(1))
                        full_url = clean_h if clean_h.startswith("http") else f"https://www.molcup.cz{clean_h}"
                        match_urls.append((m.group(1), full_url))
            except Exception:
                continue

        print(f"   -> Nalezeno {len(match_urls)} odkazů na zápasy MOL Cupu. Filtruji 1. ligu...")

        # 3. Načtení detailů zápasů
        for m_id, m_url in match_urls:
            try:
                page.goto(m_url, wait_until="domcontentloaded", timeout=20000)
                page.wait_for_timeout(400)
                body = page.inner_text("body")
                title = page.title()

                # Týmy z titulku stránky
                t_match = re.search(r'Detail zápasu\s+(.*?)\s+[\-\–]\s+(.*?)\s+[\|\-]', title)
                if t_match:
                    home, away = t_match.group(1).strip(), t_match.group(2).strip()
                else:
                    teams_match = re.search(r'([A-Za-z0-9áčďéěíňóřšťúůýžÁČĎÉĚÍŇÓŘŠŤÚŮÝŽ\s\.\-]+)\s*[\–\-]\s*([A-Za-z0-9áčďéěíňóřšťúůýžÁČĎÉĚÍŇÓŘŠŤÚŮÝŽ\s\.\-]+)', body)
                    if teams_match:
                        home = teams_match.group(1).strip().split("\n")[-1]
                        away = teams_match.group(2).strip().split("\n")[0]
                    else:
                        continue

                # STRIKTNÍ FILTR: V zápase musí hrát tým 1. české ligy!
                if not is_czech_match(home, away):
                    continue

                # Datum a čas výkopu
                d_match = re.search(r'(\d{1,2})/(\d{1,2})/(\d{4})(?:[,\s]+(\d{2}:\d{2}))?', body)
                date_str, time_str = "", ""
                if d_match:
                    d, mo, y, t = d_match.groups()
                    date_str = f"{y}-{int(mo):02d}-{int(d):02d}"
                    time_str = t or ""

                # Kolo / fáze (např. '2.kolo', '3.kolo', 'Osmifinále')
                r_match = re.search(r'(\d+\.\s*kolo|[A-Za-zčřšťžÁČĎÉĚÍŇÓŘŠŤÚŮÝŽ]+\s*finále)', body, re.IGNORECASE)
                round_name = r_match.group(1).strip() if r_match else "MOL Cup"

                # Skóre a stav
                s_match = re.search(r'(?:^|\s)(\d{1,2})\s*:\s*(\d{1,2})\s*[\.\s]*\((?:(\d{1,2})\s*:\s*(\d{1,2}))\)', body)
                if s_match:
                    hg, ag = int(s_match.group(1)), int(s_match.group(2))
                    status = "Finished"
                else:
                    simple_sc = re.search(r'(?:^|\s)(\d{1,2})\s*:\s*(\d{1,2})(?:\s|$)', body)
                    if simple_sc and ("konec" in body.lower() or "konečný" in body.lower()):
                        hg, ag = int(simple_sc.group(1)), int(simple_sc.group(2))
                        status = "Finished"
                    else:
                        hg, ag = None, None
                        status = "Scheduled"

                utc_str = ""
                if date_str and time_str:
                    try:
                        dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M").replace(tzinfo=PRAGUE_TZ)
                        utc_str = dt.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%d %H:%M UTC")
                    except Exception:
                        pass

                records.append({
                    "match_id": f"MOL_{m_id}",
                    "date": date_str,
                    "time_local": time_str,
                    "kickoff_local": f"{date_str} {time_str}".strip(),
                    "kickoff_utc": utc_str,
                    "competition": "MOL Cup",
                    "round": round_name,
                    "home_team": home,
                    "away_team": away,
                    "home_goals": hg,
                    "away_goals": ag,
                    "status": status
                })
                print(f"      ✓ MOL Cup: {date_str} {time_str} | {home} vs {away} ({status})")
            except Exception:
                continue

    except Exception as e:
        print(f"   Chyba při načítání MOL Cupu: {e}")

    print(f"   ✓ Načteno {len(records)} pohárových zápasů českých prvoligových týmů.")
    return records

# ==========================================
# 3. EVROPSKÉ POHÁRY (UEFA - LM, EL, KL)
# ==========================================
def scrape_european_cups(page):
    print("3/3 Načítám zápasy evropských pohárů (LM, EL, KL)...")
    uefa_leagues = [
        ("UEFA Champions League", "https://www.fotmob.com/leagues/42/overview/champions-league"),
        ("UEFA Europa League", "https://www.fotmob.com/leagues/73/overview/europa-league"),
        ("UEFA Conference League", "https://www.fotmob.com/leagues/10216/overview/conference-league")
    ]

    records = []
    seen = set()

    for comp_name, url in uefa_leagues:
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=40000)
            page.wait_for_timeout(2000)

            next_data_el = page.locator("#__NEXT_DATA__")
            if next_data_el.count() == 0:
                continue

            raw_json = json.loads(next_data_el.inner_text())

            # Rekurzivní vyhledání zápasů v evropské soutěži
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

                # STRIKTNÍ FILTR: Pouze zápasy, kde hraje český klub!
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
                    "match_id": f"UEFA_{m_id}",
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
        except Exception as e:
            print(f"   Chyba u {comp_name}: {e}")

    print(f"   ✓ Načteno {len(records)} zápasů českých týmů v evropských pohárech.")
    return records

# ==========================================
# HLAVNÍ SPOUŠTĚČ
# ==========================================
def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            locale="cs-CZ"
        )
        page = context.new_page()

        cl_matches = scrape_chance_liga(page)
        mol_matches = scrape_mol_cup(page)
        uefa_matches = scrape_european_cups(page)

        browser.close()

    all_records = cl_matches + mol_matches + uefa_matches
    df = pd.DataFrame(all_records)

    if not df.empty:
        df["sort_date"] = pd.to_datetime(df["date"], errors="coerce")
        df = df.sort_values(by="sort_date").drop(columns=["sort_date"])

    output_csv = "kompletni_rozpis_vsech_soutezi.csv"
    df.to_csv(output_csv, index=False, encoding="utf-8-sig")

    print(f"\n==========================================")
    print(f"HOTOVO! Celkem uloženo {len(df)} zápasů do '{output_csv}'.")
    print(f"==========================================")
    print("\nZastoupení soutěží:")
    print(df["competition"].value_counts())
    print("\nUkázka MOL Cupu a pohárů:")
    non_league = df[df["competition"] != "Chance Liga"]
    if not non_league.empty:
        print(non_league[["date", "time_local", "competition", "home_team", "away_team", "status"]].head(10))

if __name__ == "__main__":
    main()
