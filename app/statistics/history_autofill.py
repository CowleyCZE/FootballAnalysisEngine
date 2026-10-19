"""Automatic, cached historical-results discovery for the statistics engine.

The default source is the public-domain openfootball JSON catalogue. Tipsport is
kept in the news/research layer because its public results page is a current
results UI, not a stable multi-season historical feed.
"""
from __future__ import annotations

import json
import hashlib
import os
import sqlite3
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

from app.database.schema import initialize_database

GITHUB_TREE = "https://api.github.com/repos/openfootball/football.json/git/trees/master?recursive=1"
RAW_BASE = "https://raw.githubusercontent.com/openfootball/football.json/master/"
DEFAULT_CACHE = Path("data/history-cache")


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
        if os.getenv("FAE_AUTO_HISTORY", "0").lower() in {"0", "false", "no", "off"}:
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
        if not urls and code:
            urls = self._discover_openfootball_urls(code)
        if not urls:
            return {"status": "unavailable", "imported": 0, "source": None, "warnings": [f"Pro soutěž '{competition}' nebyl nalezen bezplatný strukturovaný historický zdroj."]}
        imported = 0
        used = []
        warnings = []
        for url in urls[:5]:
            try:
                rows = self._load_cached_or_remote(url)
                count = self._import_rows(rows, competition, cutoff_datetime)
                imported += count
                used.append(url)
            except Exception as exc:
                warnings.append(f"Zdroj {url}: {exc}")
        relevant = self._team_history_count(home_team_id, away_team_id, cutoff_datetime)
        if relevant:
            status = "imported" if imported else "cached"
            return {"status": status, "imported": imported, "team_matches": relevant, "source": used, "warnings": warnings}
        warnings.append(f"Ve stažené historii nebyly nalezeny zápasy týmů '{home_name}' a '{away_name}'.")
        return {"status": "no_data", "imported": imported, "source": used, "warnings": warnings}

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

    def _import_rows(self, data: dict, competition: str, cutoff_datetime: str) -> int:
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
                home_id = self._team_id(conn, home, competition)
                away_id = self._team_id(conn, away, competition)
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
    def _team_id(conn: sqlite3.Connection, name: str, competition: str) -> int:
        normalized = _norm(name)
        candidates = conn.execute("SELECT id, normalized_name FROM teams").fetchall()
        matching = []
        for ident, existing in candidates:
            existing_normalized = _norm(existing)
            if len(existing_normalized) >= 5 and (
                existing_normalized == normalized
                or existing_normalized in normalized
                or normalized in existing_normalized
            ):
                matching.append((len(existing_normalized), int(ident)))
        if matching:
            # Prefer the shortest canonical form ("Baník Ostrava") over a
            # legacy duplicate such as "FC Baník Ostrava".
            return min(matching)[1]
        return int(conn.execute("INSERT INTO teams(name, normalized_name, competition) VALUES (?,?,?)", (name, normalized, competition)).lastrowid)

    def _team_history_count(self, home_id: int, away_id: int, cutoff_datetime: str) -> int:
        with sqlite3.connect(self.db_path) as conn:
            return int(conn.execute("""SELECT count(*) FROM matches m JOIN match_statistics s ON s.match_id=m.id
                WHERE (m.home_team_id=? OR m.away_team_id=?) AND m.scheduled_at <= ?
                AND s.home_goals IS NOT NULL AND s.away_goals IS NOT NULL""", (home_id, away_id, cutoff_datetime)).fetchone()[0])
