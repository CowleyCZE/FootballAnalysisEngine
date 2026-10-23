"""Automatic, cached historical-results discovery for the statistics engine.

The default source is the public-domain openfootball JSON catalogue. Tipsport is
kept in the news/research layer because its public results page is a current
results UI, not a stable multi-season historical feed.
"""
from __future__ import annotations

import json
import hashlib
import os
import re
import sqlite3
import unicodedata
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

try:  # PyYAML je volitelné: bez něj funguje jen přesná normalizovaná shoda
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

from app.database.schema import initialize_database

GITHUB_TREE = "https://api.github.com/repos/openfootball/football.json/git/trees/master?recursive=1"
RAW_BASE = "https://raw.githubusercontent.com/openfootball/football.json/master/"
THESPORTSDB = "https://www.thesportsdb.com/api/v1/json/"
DEFAULT_CACHE = Path("data/history-cache")
ALIASES_FILE = Path(__file__).resolve().parents[2] / "config" / "team_aliases.yaml"
# Obecné klubové předpony/přípony, které nerozlišují týmy ("B" ani "U19" mezi ně nepatří).
_CLUB_TOKENS = {"fc", "fk", "sk", "ac", "as", "sc", "afc", "sfc", "ssc", "bk", "ks", "cf", "tj"}


def canonical_team_key(name: str) -> str:
    """Normalizace názvu týmu pro přesnou shodu: bez diakritiky, interpunkce a klubových předpon."""
    tokens = re.findall(r"[a-z0-9]+", _norm(name))
    if len(tokens) > 1 and tokens[0] == "1" and tokens[1] in _CLUB_TOKENS:
        tokens = tokens[1:]  # "1. FC Slovácko"
    tokens = [t for t in tokens if t not in _CLUB_TOKENS]
    return " ".join(tokens)


@lru_cache(maxsize=8)
def _load_aliases(path: str) -> dict:
    """alias (kanonický klíč) -> kanonický klíč hlavního názvu z config/team_aliases.yaml."""
    file = Path(path)
    if yaml is None or not file.exists():
        return {}
    try:
        data = yaml.safe_load(file.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {}
    result: dict = {}
    for canonical, aliases in (data.get("aliases") or {}).items():
        target = canonical_team_key(canonical)
        for alias in aliases or []:
            key = canonical_team_key(alias)
            if key and target:
                result[key] = target
    return result


def resolve_team_key(name: str) -> str:
    key = canonical_team_key(name)
    return _load_aliases(str(ALIASES_FILE)).get(key, key)


@lru_cache(maxsize=8)
def _load_alias_groups(path: str) -> tuple:
    file = Path(path)
    if yaml is None or not file.exists():
        return ()
    try:
        data = yaml.safe_load(file.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return ()
    return tuple(tuple([str(c)] + [str(a) for a in (al or [])]) for c, al in (data.get("aliases") or {}).items())


def _alias_group_names(name: str) -> list:
    """Všechny známé podoby názvu týmu z config/team_aliases.yaml (pro vyhledávání v online zdroji)."""
    key = resolve_team_key(name)
    for group in _load_alias_groups(str(ALIASES_FILE)):
        if any(resolve_team_key(n) == key for n in group):
            return list(group)
    return []


def _norm(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    return "".join(c for c in text if not unicodedata.combining(c)).lower().strip()


def _get_json(url: str, timeout: float = 20.0):
    req = Request(url, headers={"User-Agent": "FootballAnalysisEngine/1.0"})
    with urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _competition_code(competition: str) -> str | None:
    text = _norm(competition)
    if any(term in text for term in ("chance liga", "fortuna liga", "czech first", "ceska 1", "1. liga", "1 liga")):
        return "cz.1.json"
    if any(term in text for term in ("czech second", "ceska 2", "2. liga")):
        return "cz.2.json"
    return None


class HistoryAutoFiller:
    """Populate match_statistics before prediction when local history is absent."""

    def __init__(self, db_path: str = "database/football.db", cache_dir: str | Path = DEFAULT_CACHE):
        self.db_path = db_path
        self.cache_dir = Path(cache_dir)

    def ensure(self, home_team_id: int, away_team_id: int, competition: str, cutoff_datetime: str) -> dict:
        if os.getenv("FAE_AUTO_HISTORY", "1").lower() in {"0", "false", "no", "off"}:
            return {"status": "disabled", "imported": 0, "source": None, "warnings": ["FAE_AUTO_HISTORY je vypnuté."]}
        with sqlite3.connect(self.db_path) as conn:
            names = conn.execute(
                "SELECT id, name FROM teams WHERE id IN (?, ?)", (home_team_id, away_team_id)
            ).fetchall()
        if len(names) < 2:
            return {"status": "skipped", "imported": 0, "source": None, "warnings": ["Týmy nebyly nalezeny v databázi."]}
        home_name = next((name for ident, name in names if int(ident) == int(home_team_id)), "")
        away_name = next((name for ident, name in names if int(ident) == int(away_team_id)), "")
        code = _competition_code(competition)
        urls = [u.strip() for u in os.getenv("FAE_HISTORY_SOURCE_URLS", "").split(",") if u.strip()]
        warnings = []
        if not urls and code:
            try:
                urls = self._discover_openfootball_urls(code)
            except Exception as exc:
                warnings.append(f"Katalog openfootball není dostupný: {exc}")
        online_enabled = os.getenv("FAE_ONLINE_HISTORY", "1").lower() not in {"0", "false", "no", "off"}
        if not urls and not online_enabled:
            return {"status": "unavailable", "imported": 0, "source": None, "warnings": warnings + [f"Pro soutěž '{competition}' nebyl nalezen bezplatný strukturovaný historický zdroj."]}
        imported = 0
        used = []
        # Týmy cílového zápasu mají přednost: historie se musí napojit na jejich id,
        # i když v DB existují duplicity z dřívějších importů (jiný alias/předpona).
        preferred = {}
        for key, ident in ((resolve_team_key(home_name), home_team_id), (resolve_team_key(away_name), away_team_id)):
            if key:
                preferred[key] = int(ident)
        for url in urls[:5]:
            try:
                rows = self._load_cached_or_remote(url)
                count = self._import_rows(rows, competition, cutoff_datetime, preferred)
                imported += count
                used.append(url)
            except Exception as exc:
                warnings.append(f"Zdroj {url}: {exc}")
        # Aktuální výsledky: veřejné katalogy končí starými sezónami, takže poslední zápasy týmů
        # (TheSportsDB, bezplatný klíč) dotáhneme sám, když je historie prázdná nebo stará.
        if online_enabled:
            newest_local = self._newest_team_match(home_team_id, away_team_id, cutoff_datetime)
            if not self._is_recent(newest_local, cutoff_datetime, 120):
                try:
                    online_count, online_warnings = self._import_online_results(
                        [home_name, away_name], competition, cutoff_datetime, preferred)
                    imported += online_count
                    warnings.extend(online_warnings)
                    if online_count:
                        used.append("thesportsdb.com")
                except Exception as exc:
                    warnings.append(f"Online zdroj aktuálních výsledků selhal: {exc}")
        relevant = self._team_history_count(home_team_id, away_team_id, cutoff_datetime)
        if relevant:
            newest = self._newest_team_match(home_team_id, away_team_id, cutoff_datetime)
            if newest:
                try:
                    cutoff_dt = datetime.fromisoformat(str(cutoff_datetime).replace("Z", "+00:00"))
                    newest_dt = datetime.fromisoformat(str(newest).replace("Z", "+00:00"))
                    if cutoff_dt.tzinfo is None:
                        cutoff_dt = cutoff_dt.replace(tzinfo=timezone.utc)
                    if newest_dt.tzinfo is None:
                        newest_dt = newest_dt.replace(tzinfo=timezone.utc)
                    if (cutoff_dt - newest_dt).days > 400:
                        warnings.append(
                            f"Historie je zastaralá: nejnovější známý zápas týmů je z {str(newest)[:10]}. "
                            "Veřejný zdroj nemá aktuální sezóny; forma nemusí odpovídat současnosti. "
                            "Importujte aktuální výsledky: python scripts/import_history_csv.py --csv SOUBOR.csv --competition 'SOUTĚŽ'."
                        )
                except ValueError:
                    pass
            status = "imported" if imported else "cached"
            return {"status": status, "imported": imported, "team_matches": relevant, "source": used, "warnings": warnings}
        warnings.append(f"Ve stažené historii nebyly nalezeny zápasy týmů '{home_name}' a '{away_name}'.")
        return {"status": "no_data", "imported": imported, "source": used, "warnings": warnings}

    @staticmethod
    def _is_recent(newest, cutoff_datetime: str, max_days: int) -> bool:
        if not newest:
            return False
        try:
            cutoff_dt = datetime.fromisoformat(str(cutoff_datetime).replace("Z", "+00:00"))
            newest_dt = datetime.fromisoformat(str(newest).replace("Z", "+00:00"))
        except ValueError:
            return False
        if cutoff_dt.tzinfo is None:
            cutoff_dt = cutoff_dt.replace(tzinfo=timezone.utc)
        if newest_dt.tzinfo is None:
            newest_dt = newest_dt.replace(tzinfo=timezone.utc)
        return (cutoff_dt - newest_dt).days <= max_days

    def _find_online_team(self, base: str, name: str):
        key = resolve_team_key(name)
        candidates = [name] + _alias_group_names(name)
        seen = set()
        for candidate in candidates:
            if candidate in seen:
                continue
            seen.add(candidate)
            data = _get_json(base + "searchteams.php?t=" + quote(candidate), timeout=15) or {}
            for team in data.get("teams") or []:
                if str(team.get("strSport") or "").lower() != "soccer":
                    continue
                if str(team.get("strGender") or "Male").lower() == "female":
                    continue
                if resolve_team_key(team.get("strTeam") or "") == key:
                    return team
        return None

    def _import_online_results(self, team_names: list, competition: str, cutoff_datetime: str,
                               preferred: dict) -> tuple:
        """Poslední odehrané zápasy týmů z TheSportsDB (klíč FAE_THESPORTSDB_KEY, výchozí bezplatný '3')."""
        keys = [k.strip() for k in os.getenv("FAE_THESPORTSDB_KEY", "").split(",") if k.strip()] or ["123", "3"]
        base = None
        last_error = None
        for key in keys:  # bezplatný testovací klíč se u TheSportsDB měnil ("3" -> "123"); zkusíme postupně
            candidate_base = f"{THESPORTSDB}{key}/"
            try:
                _get_json(candidate_base + "searchteams.php?t=" + quote(team_names[0]), timeout=15)
                base = candidate_base
                break
            except HTTPError as exc:
                last_error = exc
                if exc.code not in (401, 403, 429):
                    raise
        if base is None:
            raise RuntimeError(f"TheSportsDB odmítl přístup (HTTP {getattr(last_error, 'code', '?')}); nastavte FAE_THESPORTSDB_KEY")
        warnings: list = []
        events: dict = {}
        for name in team_names:
            team = self._find_online_team(base, name)
            if not team:
                warnings.append(f"TheSportsDB: tým '{name}' nenalezen.")
                continue
            data = _get_json(base + "eventslast.php?id=" + quote(str(team.get("idTeam"))), timeout=15) or {}
            for ev in data.get("results") or []:
                if ev.get("idEvent"):
                    events[str(ev["idEvent"])] = ev
        if not events:
            return 0, warnings
        cutoff = datetime.fromisoformat(str(cutoff_datetime).replace("Z", "+00:00"))
        if cutoff.tzinfo is None:
            cutoff = cutoff.replace(tzinfo=timezone.utc)
        initialize_database(self.db_path)
        count = 0
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("PRAGMA foreign_keys=ON")
            for event_id, ev in events.items():
                hs, as_ = ev.get("intHomeScore"), ev.get("intAwayScore")
                date_text = str(ev.get("dateEvent") or "")
                home, away = str(ev.get("strHomeTeam") or "").strip(), str(ev.get("strAwayTeam") or "").strip()
                if hs in (None, "") or as_ in (None, "") or not date_text or not home or not away:
                    continue  # nedohraný/neznámý výsledek se nikdy nedomýšlí
                try:
                    hg, ag = int(hs), int(as_)
                    time_text = str(ev.get("strTime") or "00:00:00")[:8]
                    scheduled = datetime.fromisoformat(f"{date_text}T{time_text}").replace(tzinfo=timezone.utc)
                except ValueError:
                    continue
                if scheduled > cutoff:
                    continue
                home_id = self._team_id(conn, home, competition, preferred)
                away_id = self._team_id(conn, away, competition, preferred)
                ext = f"thesportsdb:{event_id}"
                if conn.execute("SELECT 1 FROM matches WHERE external_match_id=?", (ext,)).fetchone():
                    continue
                if conn.execute(
                    "SELECT 1 FROM matches m JOIN match_statistics s ON s.match_id=m.id "
                    "WHERE m.home_team_id=? AND m.away_team_id=? AND substr(m.scheduled_at,1,10)=?",
                    (home_id, away_id, date_text)).fetchone():
                    continue  # už importováno jiným zdrojem
                league = str(ev.get("strLeague") or competition).strip() or competition
                comp = conn.execute("SELECT id FROM competitions WHERE name=?", (league,)).fetchone()
                comp_id = int(comp[0]) if comp else int(conn.execute(
                    "INSERT INTO competitions(name, country) VALUES (?, NULL)", (league,)).lastrowid)
                match_id = int(conn.execute(
                    "INSERT INTO matches(external_match_id, competition, competition_id, season, home_team_id, away_team_id, scheduled_at, status) "
                    "VALUES (?,?,?,?,?,?,?,'RESOLVED')",
                    (ext, league, comp_id, str(ev.get("strSeason") or ""), home_id, away_id, scheduled.isoformat())).lastrowid)
                conn.execute(
                    "INSERT INTO match_statistics(match_id, home_goals, away_goals, home_ft_goals, away_ft_goals) VALUES (?,?,?,?,?) "
                    "ON CONFLICT(match_id) DO UPDATE SET home_goals=excluded.home_goals, away_goals=excluded.away_goals, "
                    "home_ft_goals=excluded.home_ft_goals, away_ft_goals=excluded.away_ft_goals",
                    (match_id, hg, ag, hg, ag))
                count += 1
            conn.commit()
        return count, warnings

    def _discover_openfootball_urls(self, file_name: str) -> list[str]:
        tree = _get_json(GITHUB_TREE)
        paths = [x["path"] for x in tree.get("tree", []) if x.get("type") == "blob" and x.get("path", "").endswith("/" + file_name)]
        paths.sort(reverse=True)
        return [RAW_BASE + path for path in paths[:3]]

    def _load_cached_or_remote(self, url: str):
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        cache_key = hashlib.sha256(url.encode("utf-8")).hexdigest()[:24]
        cache_file = self.cache_dir / (cache_key + ".json")
        max_age = int(os.getenv("FAE_HISTORY_CACHE_HOURS", "24")) * 3600
        if cache_file.exists() and (datetime.now().timestamp() - cache_file.stat().st_mtime) < max_age:
            return json.loads(cache_file.read_text(encoding="utf-8"))
        data = _get_json(url, timeout=30)
        cache_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return data

    def _import_rows(self, data: dict, competition: str, cutoff_datetime: str, preferred: dict | None = None) -> int:
        initialize_database(self.db_path)
        count = 0
        cutoff = datetime.fromisoformat(str(cutoff_datetime).replace("Z", "+00:00"))
        if cutoff.tzinfo is None:
            cutoff = cutoff.replace(tzinfo=timezone.utc)
        season = str(data.get("name", "")).rsplit(" ", 1)[-1]
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("PRAGMA foreign_keys=ON")
            comp = conn.execute("SELECT id FROM competitions WHERE name=?", (competition,)).fetchone()
            comp_id = int(comp[0]) if comp else int(conn.execute("INSERT INTO competitions(name, country) VALUES (?, 'CZ')", (competition,)).lastrowid)
            for match in data.get("matches", []):
                score = (match.get("score") or {}).get("ft")
                date_text = str(match.get("date") or "")
                if not isinstance(score, list) or len(score) < 2 or not date_text:
                    continue
                try:
                    scheduled = datetime.fromisoformat(date_text).replace(tzinfo=timezone.utc)
                except ValueError:
                    continue
                if scheduled > cutoff:
                    continue
                home, away = str(match.get("team1") or "").strip(), str(match.get("team2") or "").strip()
                if not home or not away:
                    continue
                home_id = self._team_id(conn, home, competition, preferred)
                away_id = self._team_id(conn, away, competition, preferred)
                ext = f"openfootball:{season}:{date_text}:{_norm(home)}:{_norm(away)}"
                row = conn.execute("SELECT id FROM matches WHERE external_match_id=?", (ext,)).fetchone()
                if row:
                    match_id = int(row[0])
                    # Repair rows created by an older importer version that
                    # did not strip accents or club prefixes consistently.
                    conn.execute(
                        "UPDATE matches SET competition=?, competition_id=?, season=?, home_team_id=?, away_team_id=?, scheduled_at=?, status='RESOLVED' WHERE id=?",
                        (competition, comp_id, season, home_id, away_id, scheduled.isoformat(), match_id),
                    )
                else:
                    match_id = int(conn.execute(
                        "INSERT INTO matches(external_match_id, competition, competition_id, season, home_team_id, away_team_id, scheduled_at, status) VALUES (?,?,?,?,?,?,?,'RESOLVED')",
                        (ext, competition, comp_id, season, home_id, away_id, scheduled.isoformat()),
                    ).lastrowid)
                conn.execute("""INSERT INTO match_statistics(match_id, home_goals, away_goals, home_ft_goals, away_ft_goals)
                    VALUES (?,?,?,?,?) ON CONFLICT(match_id) DO UPDATE SET home_goals=excluded.home_goals, away_goals=excluded.away_goals,
                    home_ft_goals=excluded.home_ft_goals, away_ft_goals=excluded.away_ft_goals""",
                    (match_id, int(score[0]), int(score[1]), int(score[0]), int(score[1])))
                count += 1
            conn.commit()
        return count

    @staticmethod
    def _team_id(conn: sqlite3.Connection, name: str, competition: str, preferred: dict | None = None) -> int:
        # Jen přesná shoda kanonického klíče (+ tabulka aliasů). Žádná substring shoda:
        # "Sparta Praha" a "Sparta Praha B" jsou různé týmy.
        key = resolve_team_key(name)
        if key and preferred and key in preferred:
            return int(preferred[key])  # tým cílového zápasu (řeší duplicity týmů v DB)
        if key:
            for ident, existing in conn.execute("SELECT id, name FROM teams ORDER BY id").fetchall():
                if resolve_team_key(existing) == key:
                    return int(ident)
        return int(conn.execute("INSERT INTO teams(name, normalized_name, competition) VALUES (?,?,?)", (name, _norm(name), competition)).lastrowid)

    def _team_history_count(self, home_id: int, away_id: int, cutoff_datetime: str) -> int:
        with sqlite3.connect(self.db_path) as conn:
            return int(conn.execute("""SELECT count(*) FROM matches m JOIN match_statistics s ON s.match_id=m.id
                WHERE (m.home_team_id IN (?, ?) OR m.away_team_id IN (?, ?)) AND julianday(m.scheduled_at) <= julianday(?)
                AND s.home_goals IS NOT NULL AND s.away_goals IS NOT NULL""", (home_id, away_id, home_id, away_id, cutoff_datetime)).fetchone()[0])

    def _newest_team_match(self, home_id: int, away_id: int, cutoff_datetime: str):
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute("""SELECT MAX(m.scheduled_at) FROM matches m JOIN match_statistics s ON s.match_id=m.id
                WHERE (m.home_team_id IN (?, ?) OR m.away_team_id IN (?, ?)) AND julianday(m.scheduled_at) <= julianday(?)
                AND s.home_goals IS NOT NULL AND s.away_goals IS NOT NULL""", (home_id, away_id, home_id, away_id, cutoff_datetime)).fetchone()
            return row[0] if row else None
