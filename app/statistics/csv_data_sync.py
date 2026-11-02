"""Append CSV match/team data and refresh stale Czech competition feeds.

Downloaders run in a temporary directory so their own CSV output never replaces
the user's source files. SQLite records are matched by competition, local date,
and canonical home/away team identity; old fixtures are never deleted.
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import math
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import unicodedata
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from app.database.schema import initialize_database
from app.database.team_identity import consolidate_duplicate_matches, get_or_create_team
from app.statistics.history_autofill import resolve_team_key

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA_DIR = ROOT / "database" / "data_csv"
PRAGUE = ZoneInfo("Europe/Prague")
LOG = logging.getLogger(__name__)

# TTL follows how quickly the feed changes, with a six-hour retry delay after
# failures so a broken upstream does not stall every prediction.
FEEDS = {
    "chance_liga": {"competition": "Chance Liga", "ttl": timedelta(hours=24),
                    "script": "stahni_chanceliga.py", "outputs": ["chance_liga_dataset.csv"]},
    "chance_liga_xg": {"competition": "Chance Liga", "ttl": timedelta(days=7),
                       "script": "stahni_xg_oficialni.py", "outputs": ["czech_league_xg_dataset.csv"]},
    "european_cups": {"competition": "European Cups", "ttl": timedelta(hours=24),
                       "script": "stahni_evropske_pohary.py", "outputs": ["evropske_pohary_dataset.csv"]},
    "mol_cup": {"competition": "MOL Cup", "ttl": timedelta(days=7),
                "script": "stahni_molcup.py", "outputs": ["mol_cup_dataset.csv"]},
}


def _norm_header(s: str) -> str:
    value = unicodedata.normalize("NFKD", (s or "").strip().lower())
    value = "".join(c for c in value if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "_", value).strip("_")


def _float(value: Any) -> float | None:
    try:
        if value is None or str(value).strip() == "":
            return None
        result = float(str(value).strip().replace(",", "."))
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def _int(value: Any) -> int | None:
    v = _float(value)
    return int(v) if v is not None and v.is_integer() else None


def _parse_score(value: str) -> tuple[int | None, int | None]:
    m = re.search(r"(?<!\d)(\d{1,2})\s*[-–:]\s*(\d{1,2})(?!\d)", value or "")
    return (int(m.group(1)), int(m.group(2))) if m else (None, None)


def _season(day: date) -> str:
    start = day.year if day.month >= 7 else day.year - 1
    return f"{start}-{start + 1}"


def _read_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    if "tabulka_liga" in path.name.lower():
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            raw = list(csv.reader(f))
        fields = ["squad"] + [f"home_{name}" for name in ("mp","w","d","l","gf","ga","gd","pts","ppm")] + [f"away_{name}" for name in ("mp","w","d","l","gf","ga","gd","pts","ppm")]
        rows = []
        for line in raw[2:]:
            if len(line) >= 20 and line[1].strip():
                rows.append({fields[i]: line[i+1].strip() for i in range(19)})
        return rows, fields
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        sample = f.read(4096)
        f.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel
        reader = csv.DictReader(f, dialect=dialect)
        headers = [_norm_header(h or "") for h in (reader.fieldnames or [])]
        rows = []
        for raw in reader:
            rows.append({_norm_header(k or ""): (v or "").strip() for k, v in raw.items() if k is not None})
    return rows, headers


def _pick(row: dict[str, str], *keys: str) -> str:
    for key in keys:
        if row.get(_norm_header(key), "") != "":
            return row[_norm_header(key)]
    return ""


def _team_id(conn: sqlite3.Connection, cache: dict[str, int], name: str, competition: str) -> int:
    key = resolve_team_key(name)
    if not key:
        raise ValueError("prázdný název týmu")
    if key in cache:
        return cache[key]
    cache[key] = get_or_create_team(conn, name, competition)
    return cache[key]


def _match_record(conn: sqlite3.Connection, team_ids: dict[str, int], row: dict[str, str], path: Path) -> bool:
    home = _pick(row, "home_team", "home", "squad")
    away = _pick(row, "away_team", "away")
    raw_date = _pick(row, "date", "match_date", "scheduled_at", "kickoff_local")[:10]
    if not home or not away or not raw_date:
        return False
    try:
        day = date.fromisoformat(raw_date)
    except ValueError:
        return False
    if resolve_team_key(home) == resolve_team_key(away):
        return False
    hg = _int(_pick(row, "home_goals", "fthg"))
    ag = _int(_pick(row, "away_goals", "ftag"))
    if hg is None or ag is None:
        hg, ag = _parse_score(_pick(row, "score", "result"))
    status_raw = _pick(row, "status").casefold()
    finished = hg is not None and ag is not None and status_raw not in {"scheduled", "postponed", "cancelled", "canceled"}
    comp = _pick(row, "competition") or ("Chance Liga" if "chance" in path.name.lower() or "czech_league" in path.name.lower() else "MOL Cup" if "mol" in path.name.lower() else "European Cups" if "evrops" in path.name.lower() else "Chance Liga")
    season = _season(day)
    time_raw = _pick(row, "kickoff_time", "time_local", "time")[:5]
    if not time_raw:
        kickoff_local = _pick(row, "kickoff_local")
        time_match = re.search(r"\b(\d{1,2}:\d{2})\b", kickoff_local)
        time_raw = time_match.group(1) if time_match else ""
    if time_raw == "00:00":
        time_raw = ""  # Most feeds use midnight as an unknown-time placeholder.
    time_known = False
    try:
        local_time = time.fromisoformat(time_raw) if time_raw else time(12, 0)
        time_known = bool(time_raw)
    except ValueError:
        local_time = time(12, 0)
        time_raw = ""
    scheduled = datetime.combine(day, local_time, PRAGUE).astimezone(timezone.utc).isoformat()
    kickoff_source = path.name if time_known else None
    venue = _pick(row, "venue") or None
    hid, aid = _team_id(conn, team_ids, home, comp), _team_id(conn, team_ids, away, comp)
    comp_row = conn.execute("SELECT id FROM competitions WHERE lower(name)=lower(?)", (comp,)).fetchone()
    cid = int(comp_row[0]) if comp_row else int(conn.execute("INSERT INTO competitions(name,country) VALUES(?,?)", (comp, "Czechia")).lastrowid)
    lo = datetime.combine(day, time.min, PRAGUE).astimezone(timezone.utc).isoformat()
    hi = (datetime.combine(day, time.min, PRAGUE) + timedelta(days=1)).astimezone(timezone.utc).isoformat()
    existing = conn.execute("""SELECT id FROM matches WHERE home_team_id=? AND away_team_id=?
        AND (competition_id=? OR lower(competition)=lower(?))
        AND julianday(scheduled_at)>=julianday(?) AND julianday(scheduled_at)<julianday(?)
        ORDER BY id LIMIT 1""", (hid, aid, cid, comp, lo, hi)).fetchone()
    if existing:
        mid = int(existing[0])
        if time_known:
            conn.execute("""UPDATE matches SET competition_id=?,competition=?,season=?,scheduled_at=?,kickoff_time_known=1,
                kickoff_time_source=?,venue=COALESCE(NULLIF(?,''),venue),status=?,updated_at=CURRENT_TIMESTAMP WHERE id=?""",
                (cid,comp,season,scheduled,kickoff_source,venue,"RESOLVED" if finished else "SCHEDULED",mid))
        else:
            conn.execute("""UPDATE matches SET competition_id=?,competition=?,season=?,
                scheduled_at=CASE WHEN kickoff_time_known=1 THEN scheduled_at ELSE ? END,
                venue=COALESCE(NULLIF(?,''),venue),status=?,updated_at=CURRENT_TIMESTAMP WHERE id=?""",
                (cid,comp,season,scheduled,venue,"RESOLVED" if finished else "SCHEDULED",mid))
    else:
        mid = int(conn.execute("""INSERT INTO matches(competition_id,competition,season,home_team_id,away_team_id,scheduled_at,
            kickoff_time_known,kickoff_time_source,venue,status) VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (cid,comp,season,hid,aid,scheduled,int(time_known),kickoff_source,venue,"RESOLVED" if finished else "SCHEDULED")).lastrowid)
    if finished:
        hxg, axg = _float(_pick(row, "home_xg")), _float(_pick(row, "away_xg"))
        ht_h, ht_a = _int(_pick(row, "ht_home_goals")), _int(_pick(row, "ht_away_goals"))
        sot_h, sot_a = _int(_pick(row, "home_shots_on_target")), _int(_pick(row, "away_shots_on_target"))
        poss_h, poss_a = _float(_pick(row, "home_possession_pct", "home_possession")), _float(_pick(row, "away_possession_pct", "away_possession"))
        rc_h, rc_a = _int(_pick(row, "home_red_cards")), _int(_pick(row, "away_red_cards"))
        conn.execute("""INSERT INTO match_statistics(match_id,home_goals,away_goals,home_ft_goals,away_ft_goals,
            home_ht_goals,away_ht_goals,home_shots_on_target,away_shots_on_target,home_possession,away_possession,
            home_red_cards,away_red_cards,home_xg,away_xg,home_xga,away_xga,xg_metric_definition)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(match_id) DO UPDATE SET
            home_goals=COALESCE(excluded.home_goals,home_goals),away_goals=COALESCE(excluded.away_goals,away_goals),
            home_ft_goals=COALESCE(excluded.home_ft_goals,home_ft_goals),away_ft_goals=COALESCE(excluded.away_ft_goals,away_ft_goals),
            home_ht_goals=COALESCE(excluded.home_ht_goals,home_ht_goals),away_ht_goals=COALESCE(excluded.away_ht_goals,away_ht_goals),
            home_shots_on_target=COALESCE(excluded.home_shots_on_target,home_shots_on_target),away_shots_on_target=COALESCE(excluded.away_shots_on_target,away_shots_on_target),
            home_possession=COALESCE(excluded.home_possession,home_possession),away_possession=COALESCE(excluded.away_possession,away_possession),
            home_red_cards=COALESCE(excluded.home_red_cards,home_red_cards),away_red_cards=COALESCE(excluded.away_red_cards,away_red_cards),
            home_xg=COALESCE(excluded.home_xg,home_xg),away_xg=COALESCE(excluded.away_xg,away_xg),
            home_xga=COALESCE(excluded.home_xga,home_xga),away_xga=COALESCE(excluded.away_xga,away_xga),updated_at=CURRENT_TIMESTAMP""",
            (mid,hg,ag,hg,ag,ht_h,ht_a,sot_h,sot_a,poss_h,poss_a,rc_h,rc_a,hxg,axg,axg,hxg,
             "Opta xG" if hxg is not None and axg is not None else None))
    elif "home_xg" in row and "away_xg" in row:
        hxg, axg = _float(row.get("home_xg")), _float(row.get("away_xg"))
        if hxg is not None and axg is not None:
            conn.execute("""INSERT INTO match_xg_observations(match_date,competition,season,home_team_id,away_team_id,home_xg,away_xg,source_file)
                VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(match_date,home_team_id,away_team_id,source_file) DO UPDATE SET
                home_xg=excluded.home_xg,away_xg=excluded.away_xg""",
                (day.isoformat(),comp,season,hid,aid,hxg,axg,path.name))
    return True


def _snapshot_rows(conn: sqlite3.Connection, team_ids: dict[str, int], rows: list[dict[str, str]], path: Path) -> int:
    count = 0
    cutoff = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()
    for row in rows:
        name = _pick(row, "squad", "team", "tým")
        if not name:
            continue
        season = _pick(row, "season") or "2026-2027"
        comp = _pick(row, "competition", "comp") or ("UEFA European Cups" if "svet" in path.name.lower() else "Chance Liga")
        metrics: dict[str, Any] = {}
        for k, v in row.items():
            if not k or not v:
                continue
            number = _float(v)
            metrics[k] = number if number is not None else v
        # Avoid the repeated club-only files creating semantically identical records.
        tid = _team_id(conn, team_ids, name, comp)
        conn.execute("""INSERT INTO team_season_snapshots(team_id,competition,season,data_cutoff_at,source_file,metrics_json)
            VALUES(?,?,?,?,?,?) ON CONFLICT(team_id,competition,season,data_cutoff_at,source_file)
            DO UPDATE SET metrics_json=excluded.metrics_json""",
            (tid,comp,season,cutoff,path.name,json.dumps(metrics,ensure_ascii=False,sort_keys=True)))
        count += 1
    return count


def import_csv_files(paths: list[Path], db_path: str | Path) -> dict[str, Any]:
    initialize_database(str(db_path))
    result = {"files": 0, "matches": 0, "snapshots": 0, "xg_rows": 0, "errors": []}
    with sqlite3.connect(db_path, timeout=60) as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        teams = {resolve_team_key(n): int(i) for i, n in conn.execute("SELECT id,name FROM teams")}
        for path in paths:
            try:
                rows, headers = _read_csv(path)
                if not rows:
                    continue
                result["files"] += 1
                matchish = {"date", "home_team", "away_team"}.issubset(set(headers)) or {"date", "home", "away"}.issubset(set(headers)) or {"date", "home", "score", "away"}.issubset(set(headers))
                if matchish:
                    for row in rows:
                        # Sparse xG files are observations, not fixture feeds:
                        # do not create/reset match records without results.
                        sparse_xg = ("home_xg" in headers and "away_xg" in headers
                                     and not ({"home_goals", "away_goals"}.issubset(set(headers))))
                        if sparse_xg:
                            home, away = _pick(row,"home_team"), _pick(row,"away_team")
                            try: day = date.fromisoformat(_pick(row,"date")[:10])
                            except ValueError: continue
                            comp = _pick(row,"competition") or "Chance Liga"
                            hxg, axg = _float(row.get("home_xg")), _float(row.get("away_xg"))
                            if home and away and resolve_team_key(home)!=resolve_team_key(away) and hxg is not None and axg is not None:
                                hid=_team_id(conn,teams,home,comp); aid=_team_id(conn,teams,away,comp)
                                conn.execute("""INSERT INTO match_xg_observations(match_date,competition,season,home_team_id,away_team_id,home_xg,away_xg,source_file)
                                    VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(match_date,home_team_id,away_team_id,source_file) DO UPDATE SET
                                    home_xg=excluded.home_xg,away_xg=excluded.away_xg""",
                                    (day.isoformat(),comp,_season(day),hid,aid,hxg,axg,path.name))
                                result["xg_rows"] += 1
                        elif _match_record(conn, teams, row, path):
                            result["matches"] += 1
                elif "squad" in headers and ("season" in headers or "mp" in headers or "home_mp" in headers):
                    result["snapshots"] += _snapshot_rows(conn, teams, rows, path)
                elif "tym" in headers and any(h.startswith("xg") for h in headers):
                    for row in rows:
                        name = _pick(row,"tym")
                        if not name: continue
                        tid = _team_id(conn,teams,name,"Chance Liga")
                        metrics = {k: (_float(v) if _float(v) is not None else v) for k,v in row.items() if v}
                        # The provider's aggregate columns are per-match rates;
                        # normalize names consumed by StatisticsRepository.
                        mapping = {
                            "xg_celkem": "xg_for", "xg_domaci": "xg_for_home", "xg_hoste": "xg_for_away",
                            "xga_celkem": "xg_against", "xga_domaci": "xg_against_home", "xga_hoste": "xg_against_away",
                        }
                        for source, target in mapping.items():
                            if source in metrics:
                                metrics[target] = metrics[source]
                        season = _pick(row,"season") or "2026-2027"
                        counts = conn.execute("""SELECT
                            SUM(CASE WHEN m.home_team_id=? THEN 1 ELSE 0 END),
                            SUM(CASE WHEN m.away_team_id=? THEN 1 ELSE 0 END)
                            FROM matches m JOIN match_statistics s ON s.match_id=m.id
                            WHERE (m.home_team_id=? OR m.away_team_id=?) AND m.competition='Chance Liga'
                              AND m.season=? AND s.home_goals IS NOT NULL AND s.away_goals IS NOT NULL""",
                            (tid,tid,tid,tid,season)).fetchone()
                        metrics["home_matches"] = int(counts[0] or 0)
                        metrics["away_matches"] = int(counts[1] or 0)
                        metrics["matches"] = metrics["home_matches"] + metrics["away_matches"]
                        conn.execute("""INSERT INTO team_season_snapshots(team_id,competition,season,data_cutoff_at,source_file,metrics_json)
                            VALUES(?,?,?,?,?,?) ON CONFLICT(team_id,competition,season,data_cutoff_at,source_file)
                            DO UPDATE SET metrics_json=excluded.metrics_json""",
                            (tid,"Chance Liga",season,datetime.fromtimestamp(path.stat().st_mtime,timezone.utc).isoformat(),path.name,json.dumps(metrics,ensure_ascii=False,sort_keys=True)))
                        result["snapshots"] += 1
                elif "squad" in headers and "head_to_head" in headers:
                    result["snapshots"] += _snapshot_rows(conn,teams,rows,path)
            except Exception as exc:
                result["errors"].append(f"{path}: {exc}")
        # Infer a club's home ground from the modal venue across its own home
        # fixtures; a single neutral venue cannot replace the established one.
        venue_rows = conn.execute("""SELECT m.home_team_id,m.venue,COUNT(*) n FROM matches m
            WHERE m.competition='Chance Liga' AND m.season='2026-2027' AND m.venue IS NOT NULL AND trim(m.venue)<>''
            GROUP BY m.home_team_id,m.venue ORDER BY m.home_team_id,n DESC""").fetchall()
        by_team: dict[int,list[tuple[str,int]]] = defaultdict(list)
        for team_id,venue_name,n in venue_rows: by_team[int(team_id)].append((str(venue_name),int(n)))
        for team_id, choices in by_team.items():
            if choices[0][1] < 3 or (len(choices)>1 and choices[0][1] == choices[1][1]): continue
            conn.execute("""INSERT INTO team_stadiums(team_id,stadium_name,country,source)
                VALUES(?,?,?,?) ON CONFLICT(team_id) DO UPDATE SET
                stadium_name=excluded.stadium_name,country=COALESCE(team_stadiums.country,excluded.country),
                source=excluded.source,updated_at=CURRENT_TIMESTAMP""",
                (team_id,choices[0][0],"Czechia","20261025_S&F_liga.csv"))
        consolidate_duplicate_matches(conn)
        conn.commit()
    # A previous sparse import may have downgraded a completed row. Match
    # statistics are authoritative evidence that the fixture is resolved.
    with sqlite3.connect(db_path) as conn:
        conn.execute("UPDATE matches SET status='RESOLVED' WHERE status='SCHEDULED' AND id IN (SELECT match_id FROM match_statistics WHERE home_goals IS NOT NULL AND away_goals IS NOT NULL)")
        conn.commit()
    return result


def import_existing_data(db_path: str | Path, data_dir: str | Path = DEFAULT_DATA_DIR) -> dict[str, Any]:
    root = Path(data_dir)
    paths = sorted(root.rglob("*.csv"), key=lambda p: ("czech_league_xg_dataset" not in p.name, p.as_posix()))
    # The current MOL Cup downloader still publishes its output at the project
    # root. Treat it as an explicit import source so its participants are seeded.
    molcup_export = ROOT / "molcup_vysledek.csv"
    if molcup_export.is_file():
        paths.append(molcup_export)
    result = import_csv_files(paths, db_path)
    now = datetime.now(timezone.utc).isoformat()
    # Seed per-feed freshness from the local snapshot. The downloader is eligible
    # only after its TTL elapses; a failed run retries after six hours.
    with sqlite3.connect(db_path) as conn:
        for key, feed in FEEDS.items():
            candidates = [p for p in paths if any(p.name == output or p.name.endswith(output) or ("czech_league_xg_dataset" in output and "czech_league_xg_dataset" in p.name) for output in feed["outputs"])]
            source = max(candidates,key=lambda p:p.stat().st_mtime) if candidates else None
            stamp = datetime.fromtimestamp(source.stat().st_mtime,timezone.utc).isoformat() if source else None
            if stamp:
                if key == "european_cups":
                    through = conn.execute("SELECT MAX(substr(m.scheduled_at,1,10)) FROM matches m JOIN match_statistics s ON s.match_id=m.id WHERE m.competition LIKE 'UEFA %' AND s.home_goals IS NOT NULL").fetchone()[0]
                else:
                    through = conn.execute("SELECT MAX(substr(m.scheduled_at,1,10)) FROM matches m JOIN match_statistics s ON s.match_id=m.id WHERE m.competition=? AND s.home_goals IS NOT NULL", (feed["competition"],)).fetchone()[0]
                conn.execute("""INSERT INTO competition_data_status(dataset_key,competition,last_attempt_at,last_success_at,status,source,rows_imported,data_through)
                    VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(dataset_key) DO UPDATE SET
                    last_success_at=COALESCE(competition_data_status.last_success_at,excluded.last_success_at),
                    status=CASE WHEN competition_data_status.last_success_at IS NULL THEN 'IMPORTED' ELSE competition_data_status.status END,
                    source=excluded.source,rows_imported=excluded.rows_imported,data_through=excluded.data_through""",
                    (key,feed["competition"],stamp,stamp,"IMPORTED",source.name,len(_read_csv(source)[0]),through))
        conn.commit()
    return result


def _is_stale(conn: sqlite3.Connection, key: str, ttl: timedelta, now: datetime) -> bool:
    row = conn.execute("SELECT last_success_at,last_attempt_at FROM competition_data_status WHERE dataset_key=?",(key,)).fetchone()
    if not row:
        return True
    if not row[0]:
        if row[1]:
            try:
                attempt=datetime.fromisoformat(row[1].replace("Z","+00:00"))
                if attempt.tzinfo is None: attempt=attempt.replace(tzinfo=timezone.utc)
                if now-attempt < timedelta(hours=6): return False
            except ValueError: pass
        return True
    try:
        success = datetime.fromisoformat(row[0].replace("Z","+00:00"))
        if success.tzinfo is None: success = success.replace(tzinfo=timezone.utc)
    except ValueError:
        return True
    if now-success >= ttl:
        if row[1]:
            try:
                attempt=datetime.fromisoformat(row[1].replace("Z","+00:00"))
                if attempt.tzinfo is None: attempt=attempt.replace(tzinfo=timezone.utc)
                if now-attempt < timedelta(hours=6): return False
            except ValueError: pass
        return True
    return False


def _find_feed_script(name: str) -> Path:
    """Najde downloader v kořeni projektu nebo v `database/data_csv/` (kde skutečně leží)."""
    for base in (ROOT, DEFAULT_DATA_DIR):
        candidate = base / name
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(f"Downloader {name} nenalezen v {ROOT} ani {DEFAULT_DATA_DIR}")


def refresh_stale(db_path: str | Path, *, force: bool = False) -> dict[str, Any]:
    if os.getenv("FAE_AUTO_CSV_SYNC", "1").lower() in {"0","false","no","off"} and not force:
        return {"status":"disabled","refreshed":[]}
    initialize_database(str(db_path))
    now=datetime.now(timezone.utc)
    refreshed=[]
    for key,feed in FEEDS.items():
        with sqlite3.connect(db_path,timeout=30) as conn:
            if not force and not _is_stale(conn,key,feed["ttl"],now): continue
            conn.execute("""INSERT INTO competition_data_status(dataset_key,competition,last_attempt_at,status,source)
                VALUES(?,?,?,'REFRESHING',?) ON CONFLICT(dataset_key) DO UPDATE SET last_attempt_at=excluded.last_attempt_at,status='REFRESHING',error=NULL""",
                (key,feed["competition"],now.isoformat(),feed["script"]))
            conn.commit()
        with tempfile.TemporaryDirectory(prefix=f"fae_{key}_") as temp:
            outdir=Path(temp)
            try:
                script=_find_feed_script(feed["script"])
                proc=subprocess.run([sys.executable,str(script)],cwd=outdir,env={**os.environ,"PYTHONPATH":str(ROOT)},capture_output=True,text=True,timeout=360)
                outputs=[outdir/name for name in feed["outputs"] if (outdir/name).is_file()]
                if proc.returncode != 0 or not outputs:
                    raise RuntimeError((proc.stderr or proc.stdout or f"Downloader ended with {proc.returncode}")[-4000:])
                imported=import_csv_files(outputs,db_path)
                if imported["errors"] or imported["matches"] < 1:
                    # Běh M976: zpráva končila prázdným dvojtečkou – přidán počet řádků CSV a konec výstupu downloaderu.
                    rows_in_csv = sum(len(_read_csv(p)[0]) for p in outputs)
                    tail = ((proc.stdout or "") + " " + (proc.stderr or "")).strip()[-600:]
                    raise RuntimeError(f"Stažené CSV neobsahuje importovatelná utkání (řádků v CSV: {rows_in_csv}, "
                                       f"chyby: {'; '.join(imported['errors'][:3]) or 'žádné'}). Výstup downloaderu: {tail or '(prázdný)'}")
                with sqlite3.connect(db_path) as conn:
                    if key == "european_cups":
                        through=conn.execute("SELECT MAX(substr(m.scheduled_at,1,10)) FROM matches m JOIN match_statistics s ON s.match_id=m.id WHERE m.competition LIKE 'UEFA %' AND s.home_goals IS NOT NULL").fetchone()[0]
                    else:
                        through=conn.execute("SELECT MAX(substr(m.scheduled_at,1,10)) FROM matches m JOIN match_statistics s ON s.match_id=m.id WHERE m.competition=? AND s.home_goals IS NOT NULL",(feed["competition"],)).fetchone()[0]
                    conn.execute("""UPDATE competition_data_status SET last_success_at=?,status='OK',source=?,rows_imported=?,data_through=?,error=NULL,updated_at=CURRENT_TIMESTAMP WHERE dataset_key=?""",
                                 (datetime.now(timezone.utc).isoformat(),feed["script"],imported["matches"],through,key))
                    conn.commit()
                refreshed.append({"dataset":key,"status":"OK","matches":imported["matches"]})
            except Exception as exc:
                LOG.warning("CSV feed refresh %s failed: %s",key,exc)
                with sqlite3.connect(db_path) as conn:
                    conn.execute("UPDATE competition_data_status SET status='ERROR',error=?,updated_at=CURRENT_TIMESTAMP WHERE dataset_key=?",(str(exc)[:4000],key))
                    conn.commit()
                refreshed.append({"dataset":key,"status":"ERROR","error":str(exc)})
    return {"status":"COMPLETED","refreshed":refreshed}


def freshness_report(db_path: str | Path) -> list[dict[str, Any]]:
    initialize_database(str(db_path))
    now=datetime.now(timezone.utc)
    with sqlite3.connect(db_path) as conn:
        rows=conn.execute("SELECT dataset_key,competition,last_success_at,data_through,status,error FROM competition_data_status ORDER BY competition,dataset_key").fetchall()
    output=[]
    for key,comp,success,through,status,error in rows:
        ttl=FEEDS.get(key,{}).get("ttl",timedelta(days=30))
        try:
            stamp=datetime.fromisoformat(success.replace("Z","+00:00")) if success else None
            if stamp and stamp.tzinfo is None: stamp=stamp.replace(tzinfo=timezone.utc)
            age_hours=round((now-stamp).total_seconds()/3600,1) if stamp else None
        except ValueError: age_hours=None
        output.append({"dataset":key,"competition":comp,"last_success_at":success,"age_hours":age_hours,"ttl_hours":ttl.total_seconds()/3600,"data_through":through,"stale":age_hours is None or age_hours>=ttl.total_seconds()/3600,"status":status,"error":error})
    return output


def main() -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db",type=Path,default=ROOT/"database/football.db")
    parser.add_argument("--data-dir",type=Path,default=DEFAULT_DATA_DIR)
    parser.add_argument("--import-existing",action="store_true")
    parser.add_argument("--refresh",action="store_true",help="force all download feeds")
    parser.add_argument("--status",action="store_true")
    args=parser.parse_args()
    if args.import_existing:
        result=import_existing_data(args.db,args.data_dir)
        print(json.dumps(result,ensure_ascii=False,indent=2))
        return int(bool(result["errors"]))
    if args.status:
        print(json.dumps(freshness_report(args.db),ensure_ascii=False,indent=2))
        return 0
    result=refresh_stale(args.db,force=args.refresh)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
