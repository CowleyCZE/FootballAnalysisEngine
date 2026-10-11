# -*- coding: utf-8 -*-

import json
import sqlite3
import sys
from datetime import datetime, timezone
from typing import List, Any, Optional

try:
    from zoneinfo import ZoneInfo
except ImportError:  # Python < 3.9
    ZoneInfo = None  # type: ignore
    sys.exit("Je vyžadován Python 3.9+ (zoneinfo).")

from app.orchestrator.orchestrator import MasterOrchestrator

DB_PATH = "database/football.db"
DEFAULT_TZ = "Europe/Prague"


# ---------------------------------------------------------------------------
# Pomocné funkce
# ---------------------------------------------------------------------------

def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def input_required(prompt: str) -> str:
    while True:
        value = input(prompt).strip()
        if value:
            return value
        print("  ! Hodnota nesmí být prázdná, zkuste to znovu.")


def parse_datetime(text: str, tz_name: str) -> datetime:
    """Parsuje 'DD.MM.YYYY HH:MM' nebo 'YYYY-MM-DD HH:MM' a převádí na UTC."""
    text = text.strip()
    dt = None
    for fmt in ("%d.%m.%Y %H:%M", "%Y-%m-%d %H:%M",
                "%d.%m.%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S",
                "%d.%m.%Y", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(text, fmt)
            break
        except ValueError:
            continue

    if dt is None:
        raise ValueError("Neplatný formát data a času (očekáváno DD.MM.YYYY HH:MM nebo YYYY-MM-DD HH:MM).")

    try:
        tz = ZoneInfo(tz_name)
    except Exception as e:
        raise ValueError(f"Neplatné časové pásmo '{tz_name}': {e}")
    return dt.replace(tzinfo=tz).astimezone(timezone.utc)


def normalize_name(name: str) -> str:
    return " ".join(name.strip().lower().split())


def get_or_create_team(cursor: sqlite3.Cursor, name: str) -> int:
    norm = normalize_name(name)
    row = cursor.execute(
        "SELECT id FROM teams WHERE normalized_name = ? OR lower(name) = ?", (norm, norm)
    ).fetchone()
    if row:
        return int(row["id"])
    cursor.execute(
        "INSERT INTO teams (name, normalized_name) VALUES (?, ?)", (name.strip(), norm)
    )
    return int(cursor.lastrowid)


def get_or_create_competition(cursor: sqlite3.Cursor, name: str) -> int:
    norm = normalize_name(name)
    # SQLite's built-in lower() is ASCII-only, so it does not reliably match
    # Czech names containing uppercase accented characters (for example Č).
    rows = cursor.execute("SELECT id, name FROM competitions").fetchall()
    for row in rows:
        if normalize_name(row["name"]) == norm:
            return int(row["id"])

    # Ignore a concurrent insert racing between the lookup and insert, then
    # resolve the canonical row using the same Unicode-aware normalization.
    cursor.execute("INSERT OR IGNORE INTO competitions (name) VALUES (?)", (name.strip(),))
    if cursor.rowcount:
        return int(cursor.lastrowid)
    rows = cursor.execute("SELECT id, name FROM competitions").fetchall()
    for row in rows:
        if normalize_name(row["name"]) == norm:
            return int(row["id"])
    raise sqlite3.IntegrityError(f"Soutěž '{name}' již existuje, ale nelze ji načíst.")


def list_matches() -> List[sqlite3.Row]:
    conn = get_connection()
    rows = conn.execute("""
        SELECT m.id, m.status, m.scheduled_at, m.competition,
               th.name AS home_team, ta.name AS away_team
        FROM matches m
        LEFT JOIN teams th ON m.home_team_id = th.id
        LEFT JOIN teams ta ON m.away_team_id = ta.id
        ORDER BY m.scheduled_at, m.id
    """).fetchall()
    conn.close()
    return rows


def print_matches(rows: List[sqlite3.Row]) -> None:
    if not rows:
        print("\n  (Žádné zápasy v databázi.)")
        return
    print(f"\n  {'ID':<5} {'Domácí':<22} {'Hostující':<22} {'Soutěž':<20} {'Datum a čas':<20} {'Stav':<10}")
    print("  " + "-" * 100)
    for r in rows:
        # SQLite allows nullable legacy values, and LEFT JOIN can produce a
        # missing team name.  Convert to strings before applying width specs:
        # formatting None with '<22' raises TypeError in Python.
        values = (
            r["id"],
            r["home_team"] or "?",
            r["away_team"] or "?",
            r["competition"] or "?",
            r["scheduled_at"] or "?",
            r["status"] or "?",
        )
        match_id, home, away, competition, scheduled_at, status = values
        print(f"  {match_id:<5} {home:<22} {away:<22} "
              f"{competition:<20} {scheduled_at:<20} {status:<10}")


def matches_with_runs() -> List[sqlite3.Row]:
    conn = get_connection()
    rows = conn.execute("""
        SELECT DISTINCT m.id, th.name AS home_team, ta.name AS away_team,
               m.competition, m.scheduled_at,
               p.run_id, p.state, p.cycle, p.max_cycles
        FROM pipeline_runs p
        JOIN matches m ON p.match_id = m.id
        LEFT JOIN teams th ON m.home_team_id = th.id
        LEFT JOIN teams ta ON m.away_team_id = ta.id
        ORDER BY m.id, p.started_at
    """).fetchall()
    conn.close()
    return rows


def select_match(prompt: str = "Zadejte ID zápasu: ") -> Optional[int]:
    raw = input(prompt).strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        print("  ! Neplatné ID (očekáváno celé číslo).")
        return None


# ---------------------------------------------------------------------------
# 1. Přidat nový zápas
# ---------------------------------------------------------------------------

def add_match() -> None:
    print("\n=== Přidat nový zápas ===")
    home = input_required("Domácí tým (např. 'Sparta Praha'): ")
    away = input_required("Hostující tým (např. 'Slavia Praha'): ")
    competition = input_required("Název soutěže (např. 'Chance Liga'): ")
    datetime_text = input_required("Datum a čas zápasu (DD.MM.YYYY HH:MM nebo YYYY-MM-DD HH:MM): ")
    tz_name = input(f"Časové pásmo [{DEFAULT_TZ}]: ").strip() or DEFAULT_TZ

    try:
        kickoff_utc = parse_datetime(datetime_text, tz_name)
    except ValueError as e:
        print(f"  ! {e}")
        return

    conn = get_connection()
    try:
        cursor = conn.cursor()
        home_id = get_or_create_team(cursor, home)
        away_id = get_or_create_team(cursor, away)
        comp_id = get_or_create_competition(cursor, competition)

        cursor.execute("""
            INSERT INTO matches (home_team_id, away_team_id, competition_id, competition, scheduled_at, status)
            VALUES (?, ?, ?, ?, ?, 'RESOLVED')
        """, (home_id, away_id, comp_id, competition, kickoff_utc.isoformat()))
        match_id = int(cursor.lastrowid)
        conn.commit()
        print(f"\n  ✔ Zápas #{match_id} uložen: "
              f"{home} vs {away} ({competition}), {kickoff_utc.strftime('%Y-%m-%d %H:%M UTC')}")
        print("  Spouštím analýzu.")
        cutoff_utc = datetime.now(timezone.utc)
        try:
            orchestrator = MasterOrchestrator(db_path=DB_PATH)
            run_id = orchestrator.start_pipeline(
                match_id,
                data_cutoff_at=cutoff_utc,
            )
            print(f"  ✔ Analýza spuštěna. Run ID: {run_id}")
        except Exception as e:
            print(f"  ! Zápas je uložen, ale analýzu se nepodařilo spustit: {e}")
    except sqlite3.Error as e:
        conn.rollback()
        print(f"  ! Chyba při ukládání do databáze: {e}")
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 2. Spustit analýzu
# ---------------------------------------------------------------------------

def run_analysis() -> None:
    print("\n=== Spustit analýzu ===")
    rows = list_matches()
    print_matches(rows)
    if not rows:
        return
    match_id = select_match("Vyberte zápas podle ID: ")
    if match_id is None:
        return

    cutoff_text = input(
        "Data cutoff (DD.MM.YYYY HH:MM nebo YYYY-MM-DD HH:MM; Enter = aktuální čas UTC): "
    ).strip()
    if cutoff_text:
        tz_name = input(f"Časové pásmo cutoffu [{DEFAULT_TZ}]: ").strip() or DEFAULT_TZ
        try:
            cutoff_utc = parse_datetime(cutoff_text, tz_name)
        except ValueError as e:
            print(f"  ! {e}")
            return
    else:
        cutoff_utc = datetime.now(timezone.utc)

    try:
        orchestrator = MasterOrchestrator(db_path=DB_PATH)
        run_id = orchestrator.start_pipeline(
            match_id,
            data_cutoff_at=cutoff_utc,
        )
        print(f"\n  ✔ Pipeline spuštěna přes MasterOrchestrator.")
        print(f"    Run ID: {run_id}")
        print("    Stav analýzy sledujete volbou 5 (Kontrola stavu analýzy).")
    except ValueError as e:
        print(f"  ! {e}")
    except Exception as e:
        print(f"  ! Nepodařilo se spustit pipeline: {e}")


# ---------------------------------------------------------------------------
# 3. Zápasy s analýzou
# ---------------------------------------------------------------------------

def show_matches_with_analysis() -> None:
    print("\n=== Zápasy s analýzou ===")
    rows = matches_with_runs()
    if not rows:
        print("  (Žádný zápas nemá spuštěnou analýzu.)")
        return
    print(f"\n  {'ID':<5} {'Zápas':<45} {'Run ID':<30} {'Stav pipeline':<14} {'Cyklus':<10}")
    print("  " + "-" * 110)
    for r in rows:
        label = f"{r['home_team']} vs {r['away_team']}"
        print(f"  {r['id']:<5} {label:<45} {r['run_id']:<30} {r['state']:<14} {r['cycle']}/{r['max_cycles']:<8}")


# ---------------------------------------------------------------------------
# 4. Výsledky analýzy
# ---------------------------------------------------------------------------

def show_analysis_results() -> None:
    print("\n=== Výsledky analýzy ===")
    rows = matches_with_runs()
    if not rows:
        print("  (Žádný zápas nemá spuštěnou analýzu.)")
        return
    print(f"\n  {'ID':<5} {'Zápas':<45} {'Poslední Run ID':<30}")
    print("  " + "-" * 85)
    for r in rows:
        label = f"{r['home_team']} vs {r['away_team']}"
        print(f"  {r['id']:<5} {label:<45} {r['run_id']:<30}")

    match_id = select_match("Vyberte zápas podle ID: ")
    if match_id is None:
        return

    conn = get_connection()

    match = conn.execute("""
        SELECT m.id, m.scheduled_at, m.competition,
               th.name AS home_team, ta.name AS away_team
        FROM matches m
        LEFT JOIN teams th ON m.home_team_id = th.id
        LEFT JOIN teams ta ON m.away_team_id = ta.id
        WHERE m.id = ?
    """, (match_id,)).fetchone()
    if not match:
        print("  ! Zápas nenalezen.")
        conn.close()
        return

    pipeline = conn.execute(
        "SELECT * FROM pipeline_runs WHERE match_id = ? ORDER BY started_at DESC LIMIT 1", (match_id,)
    ).fetchone()

    print("\n  --- Základní info ---")
    print(f"  Zápas:      {match['home_team']} vs {match['away_team']}")
    print(f"  Soutěž:     {match['competition'] or '?'}")
    print(f"  Datum:      {match['scheduled_at'] or '?'}")

    run_id = pipeline["run_id"] if pipeline else None

    # Produkční AIWorker ukládá výsledek do jobs.result_json, ne do ai_runs.
    ai = conn.execute(
        "SELECT status, result_json, error_text FROM jobs "
        "WHERE run_id = ? AND job_type = 'AI_ANALYSIS' ORDER BY id DESC LIMIT 1",
        (run_id,),
    ).fetchone() if run_id else None
    print("\n  --- AI Analýza ---")
    if ai:
        print(f"  Stav jobu: {ai['status']}")
        raw = ai["result_json"]
        if raw:
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    print(f"  Stav analýzy: {parsed.get('status', '?')}")
                    conclusion = parsed.get("conclusion") or parsed.get("summary")
                    if conclusion:
                        print(f"  Závěr: {conclusion}")
                    teams_analysis = parsed.get("teams") or parsed.get("team_analysis")
                    if teams_analysis:
                        print(f"  Analýza týmů: {json.dumps(teams_analysis, ensure_ascii=False, indent=2)[:1500]}")
                    key_factors = parsed.get("key_factors")
                    if key_factors:
                        print(f"  Klíčové faktory: {json.dumps(key_factors, ensure_ascii=False, indent=2)[:1500]}")
                    if not conclusion and not teams_analysis and not key_factors:
                        print(f"  Odpověď: {json.dumps(parsed, ensure_ascii=False)[:2000]}")
                else:
                    print(f"  Odpověď: {json.dumps(parsed, ensure_ascii=False)[:2000]}")
            except (ValueError, TypeError):
                print(f"  Odpověď: {str(raw)[:2000]}")
        elif ai["error_text"]:
            print(f"  Chyba: {ai['error_text']}")
        else:
            print("  Job zatím neobsahuje výsledek.")
    else:
        print("  (Zatím žádná AI analýza v tomto běhu.)")

    # Audit
    audit = conn.execute(
        "SELECT status, result_json, error_text FROM jobs "
        "WHERE run_id = ? AND job_type = 'AUDIT' ORDER BY id DESC LIMIT 1",
        (run_id,),
    ).fetchone() if run_id else None
    print("\n  --- Audit ---")
    if audit:
        print(f"  Stav jobu: {audit['status']}")
        if audit["result_json"]:
            try:
                audit_result = json.loads(audit["result_json"])
                print(f"  Výsledek auditu: {audit_result.get('status', '?')}  |  "
                      f"Skóre: {audit_result.get('audit_score', '?')}")
                for issue in audit_result.get("issues", [])[:20]:
                    print(f"    [{issue.get('severity', '?')}] {issue.get('type', '')}: "
                          f"{issue.get('description', '')}")
            except (ValueError, TypeError):
                print(f"  Nečitelný výsledek auditu: {str(audit['result_json'])[:1000]}")
        elif audit["error_text"]:
            print(f"  Chyba: {audit['error_text']}")
        else:
            print("  Job zatím neobsahuje výsledek.")
    else:
        print("  (V tomto běhu zatím nebyl spuštěn audit.)")

    # Claims
    run_db = conn.execute("SELECT id FROM runs WHERE run_id = ?", (run_id,)).fetchone() if run_id else None
    claims = conn.execute(
        "SELECT claim_text, status, confidence FROM claims WHERE run_id = ? ORDER BY id DESC LIMIT 30",
        (run_db["id"],),
    ).fetchall() if run_db else []
    print("\n  --- Claims ---")
    if claims:
        for c in claims:
            conf = f"{c['confidence']:.2f}" if c["confidence"] is not None else "?"
            print(f"    [{c['status']}] (důvěryhodnost {conf}) {c['claim_text'][:120]}")
    else:
        print("  (Žádná tvrzení.)")

    # Statistiky a snapshoty
    print("\n  --- Statistiky ---")
    run_db = conn.execute("SELECT id FROM runs WHERE run_id = ?", (run_id,)).fetchone() if run_id else None
    snapshots = conn.execute(
        "SELECT s.*, t.name as team_name "
        "FROM statistical_snapshots s "
        "LEFT JOIN teams t ON s.team_id = t.id "
        "WHERE s.run_id = ? "
        "ORDER BY s.id",
        (run_db["id"],),
    ).fetchall() if run_db else []

    if snapshots:
        print(f"  {'Tým':<20} {'Metrika':<15} {'Hodnota':<10} {'Sample':<8} {'Coverage':<10} {'Cutoff':<20}")
        print("  " + "-" * 85)
        for snap in snapshots:
            tname = snap["team_name"] or "Zápas/Celkem"
            val = f"{snap['value']:.2f}" if snap["value"] is not None else "N/A"
            cov = f"{snap['coverage'] * 100:.0f}%" if snap["coverage"] is not None else "?"
            cutoff_val = snap["data_cutoff_at"][:19] if snap["data_cutoff_at"] else "?"
            print(f"  {tname:<20} {snap['metric']:<15} {val:<10} {snap['sample_size']:<8} {cov:<10} {cutoff_val:<20}")
    else:
        stats = conn.execute(
            "SELECT * FROM match_statistics WHERE match_id = ?", (match_id,)
        ).fetchone()
        if stats:
            keys = ["home_goals", "away_goals", "home_shots", "away_shots",
                    "home_shots_on_target", "away_shots_on_target",
                    "home_possession", "away_possession", "home_corners", "away_corners",
                    "home_yellow_cards", "away_yellow_cards", "home_red_cards", "away_red_cards",
                    "home_xg", "away_xg"]
            for k in keys:
                if stats[k] is not None:
                    print(f"    {k}: {stats[k]}")
        else:
            print("  (Žádné statistické snapshoty pro tento run.)")

    stats_job = conn.execute(
        "SELECT result_json, error_text FROM jobs WHERE run_id = ? AND job_type = 'STATISTICS' ORDER BY id DESC LIMIT 1",
        (run_id,),
    ).fetchone() if run_id else None
    if stats_job:
        if stats_job["result_json"]:
            try:
                res_dict = json.loads(stats_job["result_json"])
                warns = res_dict.get("warnings", []) if isinstance(res_dict, dict) else []
                if warns:
                    print("\n  Varování statistik:")
                    for w in warns:
                        print(f"    ! {w}")
            except Exception:
                pass
        elif stats_job["error_text"]:
            print(f"\n  Chyba výpočtu statistik: {stats_job['error_text']}")

    # Stav pipeline
    print("\n  --- Stav pipeline ---")
    if pipeline:
        jobs = conn.execute(
            "SELECT status, COUNT(*) AS cnt FROM jobs WHERE run_id = ? GROUP BY status", (pipeline["run_id"],)
        ).fetchall()
        print(f"  Run ID: {pipeline['run_id']}  |  Stav: {pipeline['state']}  |  "
              f"Cyklus: {pipeline['cycle']}/{pipeline['max_cycles']}")
        for j in jobs:
            print(f"    {j['status']}: {j['cnt']} jobů")
    else:
        print("  (Žádný pipeline run.)")

    conn.close()


# ---------------------------------------------------------------------------
# 5. Stav analýzy
# ---------------------------------------------------------------------------

def check_analysis_status() -> None:
    print("\n=== Stav analýzy ===")
    rows = matches_with_runs()
    if not rows:
        print("  (Žádný zápas nemá spuštěnou analýzu.)")
        return
    for r in rows:
        label = f"{r['home_team']} vs {r['away_team']}"
        print(f"  [{r['id']}] {label}  ->  Run ID: {r['run_id']}  ({r['state']})")

    match_id = select_match("Vyberte zápas podle ID: ")
    if match_id is None:
        return

    conn = get_connection()
    pipeline = conn.execute(
        "SELECT * FROM pipeline_runs WHERE match_id = ? ORDER BY started_at DESC LIMIT 1", (match_id,)
    ).fetchone()
    if not pipeline:
        print("  ! Pro tento zápas neexistuje pipeline run.")
        conn.close()
        return

    print(f"\n  Run ID: {pipeline['run_id']}")
    print(f"  Stav:   {pipeline['state']}  |  Cyklus: {pipeline['cycle']}/{pipeline['max_cycles']}")
    print(f"  Start:  {pipeline['started_at']}  |  Poslední aktualizace: {pipeline['updated_at']}")
    if pipeline["error_text"]:
        print(f"  Chyba:  {pipeline['error_text']}")

    jobs = conn.execute(
        "SELECT job_type, status, COUNT(*) AS cnt FROM jobs WHERE run_id = ? GROUP BY job_type, status ORDER BY job_type",
        (pipeline["run_id"],)
    ).fetchall()
    print("\n  Joby pipeline:")
    if jobs:
        print(f"    {'Typ':<14} {'Stav':<10} {'Počet':<6}")
        print("    " + "-" * 35)
        for j in jobs:
            print(f"    {j['job_type']:<14} {j['status']:<10} {j['cnt']:<6}")
    else:
        print("    (Žádné joby.)")

    detail = conn.execute(
        "SELECT job_id, job_type, status, attempts, error_text FROM jobs WHERE run_id = ? ORDER BY id", (pipeline["run_id"],)
    ).fetchall()
    if detail:
        print("\n  Detail jobů:")
        for j in detail[:50]:
            extra = f"  ! {j['error_text'][:80]}" if j["error_text"] else ""
            print(f"    [{j['status']:<8}] {j['job_type']:<14} ({(j['job_id'] or '')[:13]}…, pokusy: {j['attempts']}){extra}")

    conn.close()


# ---------------------------------------------------------------------------
# 6. Všechny zápasy
# ---------------------------------------------------------------------------

def show_all_matches() -> None:
    print("\n=== Všechny zápasy ===")
    print_matches(list_matches())


# ---------------------------------------------------------------------------
# Hlavní smyčka
# ---------------------------------------------------------------------------

MENU = """
========================================
   FOOTBALL ANALYSIS ENGINE — MENU
========================================
Hlavní menu:
  1. Přidat nový zápas
  2. Spustit analýzu pro zápas
  3. Zobrazit zápasy s analýzou
  4. Zobrazit výsledky analýzy
  5. Zkontrolovat stav analýzy
  6. Zobrazit všechny zápasy
  7. Konec
"""

ACTIONS = {
    "1": ("Přidat nový zápas", add_match),
    "2": ("Spustit analýzu pro zápas", run_analysis),
    "3": ("Zobrazit zápasy s analýzou", show_matches_with_analysis),
    "4": ("Zobrazit výsledky analýzy", show_analysis_results),
    "5": ("Zkontrolovat stav analýzy", check_analysis_status),
    "6": ("Zobrazit všechny zápasy", show_all_matches),
}


def main() -> None:
    while True:
        print(MENU)
        choice = input("Vyberte volbu (1-7): ").strip()
        if choice == "7":
            print("Ukončuji. Na shledanou!")
            break
        action = ACTIONS.get(choice)
        if not action:
            print("  ! Neplatná volba, zkuste to znovu.")
            continue
        try:
            action[1]()
        except KeyboardInterrupt:
            print("\n  (Akce přerušena.)")
        except Exception as e:
            print(f"  ! Neočekávaná chyba: {e}")
        input("\nStiskněte Enter pro návrat do menu...")


if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, EOFError):
        print("\nUkončuji. Na shledanou!")
