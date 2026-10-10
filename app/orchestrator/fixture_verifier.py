"""Evidence-backed fixture verification.

Only a pair of independent official sources that explicitly report the teams, order,
competition and exact kickoff may transition a scheduled fixture to RESOLVED.
"""
from __future__ import annotations

import asyncio
import json
import re
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from app.search.engine import SearchEngine
from app.search.models import QuerySpec
from app.search.normalizer import normalize_searx_result


class FixtureVerificationError(RuntimeError):
    """Raised if the fixture is missing or cannot be verified."""


OFFICIAL_SCHEDULE_DOMAINS = {
    "chanceliga.cz",
    "sparta.cz",
    "fkpardubice.cz",
    "fotbal.cz",
}


def _domain(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def _normal(text: str) -> str:
    # Transliterate common Czech characters before removing punctuation.
    table = str.maketrans({
        "á": "a", "č": "c", "ď": "d", "é": "e", "ě": "e",
        "í": "i", "ň": "n", "ó": "o", "ř": "r", "š": "s",
        "ť": "t", "ú": "u", "ů": "u", "ý": "y", "ž": "z",
    })
    text = (text or "").casefold().translate(table)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


class FixtureVerifier:
    def __init__(
        self,
        db_path: str = "database/football.db",
        search_engine: SearchEngine | None = None,
        official_domains: set[str] | None = None,
    ):
        self.db_path = db_path
        self.search_engine = search_engine or SearchEngine()
        self.official_domains = {
            _domain("https://" + d) for d in (official_domains or OFFICIAL_SCHEDULE_DOMAINS)
        }

    def verify_sync(self, match_id: int) -> dict[str, Any]:
        """Synchronous wrapper usable from CLI, worker threads and FastAPI."""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.verify(match_id))

        values: list[dict[str, Any]] = []
        errors: list[BaseException] = []

        def run() -> None:
            try:
                values.append(asyncio.run(self.verify(match_id)))
            except BaseException as exc:
                errors.append(exc)

        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        thread.join()
        if errors:
            raise errors[0]
        if not values:
            raise FixtureVerificationError("Ověřování skončilo bez výsledku.")
        return values[0]

    @staticmethod
    def _local_datetime(value: str) -> datetime:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            return dt.replace(tzinfo=ZoneInfo("Europe/Prague"))
        return dt.astimezone(ZoneInfo("Europe/Prague"))

    @staticmethod
    def _parse_candidate_datetime(text: str) -> datetime | None:
        patterns = (
            r"(?P<day>\d{1,2})\s*[./]\s*(?P<month>\d{1,2})\s*[./]\s*(?P<year>20\d{2})\.?\s*[ ,T]+\s*(?P<hour>\d{1,2}):(?P<minute>\d{2})",
            r"(?P<year>20\d{2})-(?P<month>\d{1,2})-(?P<day>\d{1,2})[ T]+(?P<hour>\d{1,2}):(?P<minute>\d{2})",
        )
        for pattern in patterns:
            found = re.search(pattern, text)
            if not found:
                continue
            values = found.groupdict()
            try:
                return datetime(
                    int(values["year"]), int(values["month"]), int(values["day"]),
                    int(values["hour"]), int(values["minute"]),
                )
            except ValueError:
                continue
        return None

    @staticmethod
    def _fixture_pair_ok(text: str, home: str, away: str) -> bool:
        # Locate full team names in the original string so punctuation between
        # them (for example the dash in "Sparta - Pardubice") remains available.
        raw = (text or "").casefold()
        home_raw, away_raw = home.casefold(), away.casefold()
        home_pos, away_pos = raw.find(home_raw), raw.find(away_raw)
        if home_pos < 0 or away_pos < 0 or home_pos >= away_pos:
            return False
        between = raw[home_pos + len(home_raw):away_pos]
        # Both teams must form one explicit fixture pair, not unrelated mentions.
        return bool(re.search(r"\b(vs|v|versus|at)\b|[-–]", between))
    @staticmethod
    def _competition_ok(text: str, competition: str) -> bool:
        normalized_text = _normal(text)
        normalized_comp = _normal(competition)
        aliases = {
            "ceska chance liga": ("ceska chance liga", "chance liga"),
            "chance liga": ("chance liga", "ceska chance liga"),
        }
        return any(
            _normal(candidate) in normalized_text
            for candidate in aliases.get(normalized_comp, (normalized_comp,))
            if candidate
        )

    async def verify(self, match_id: int) -> dict[str, Any]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            match = conn.execute(
                """SELECT m.id, m.status, m.scheduled_at,
                          COALESCE(c.name, m.competition, '') AS competition_name,
                          th.name AS home_team, ta.name AS away_team
                   FROM matches m
                   JOIN teams th ON th.id=m.home_team_id
                   JOIN teams ta ON ta.id=m.away_team_id
                   LEFT JOIN competitions c ON c.id=m.competition_id
                   WHERE m.id=?""",
                (match_id,),
            ).fetchone()
        if not match:
            raise FixtureVerificationError(f"Zápas ID {match_id} nebyl nalezen.")
        if not match["scheduled_at"]:
            raise FixtureVerificationError(f"Zápas ID {match_id} nemá čas výkopu.")

        kickoff = self._local_datetime(match["scheduled_at"])
        competition = str(match["competition_name"] or "").strip()
        if not competition:
            raise FixtureVerificationError("Zápas nemá určenou soutěž.")

        # Search both schedule-specific and Czech-language variants through the existing
        # SearXNG backend. A failure is recorded as an unsuccessful attempt.
        date_iso = kickoff.strftime("%Y-%m-%d")
        date_local = kickoff.strftime("%d.%m.%Y")
        time_local = kickoff.strftime("%H:%M")
        queries = [
            QuerySpec(
                query=f'"{match["home_team"]}" "{match["away_team"]}" {date_iso}',
                language="all", priority=100, reason="FIXTURE_VERIFICATION",
            ),
            QuerySpec(
                query=f'"{match["home_team"]}" "{match["away_team"]}" {date_local}',
                language="cs", priority=100, reason="FIXTURE_VERIFICATION",
            ),
            QuerySpec(
                query=f'"{match["home_team"]}" "{match["away_team"]}" "{competition}"',
                language="all", priority=95, reason="FIXTURE_VERIFICATION",
            ),
            QuerySpec(
                query=f'site:chanceliga.cz "{match["home_team"]}" "{match["away_team"]}"',
                language="cs", priority=100, reason="FIXTURE_VERIFICATION",
            ),
            QuerySpec(
                query=f'site:fkpardubice.cz "{match["home_team"]}" "{match["away_team"]}"',
                language="cs", priority=100, reason="FIXTURE_VERIFICATION",
            ),
            QuerySpec(
                query=f'site:sparta.cz "{match["home_team"]}" "{match["away_team"]}"',
                language="cs", priority=100, reason="FIXTURE_VERIFICATION",
            ),
        ]
        raw_results = []
        search_errors = []
        for query in queries:
            try:
                response = await self.search_engine.client.search(
                    query.query, language=query.language, time_range=None
                )
                items = response if isinstance(response, list) else response.get("results", []) if isinstance(response, dict) else []
                raw_results.extend(normalize_searx_result(item) for item in items if isinstance(item, dict))
            except Exception as exc:
                search_errors.append(f"{type(exc).__name__}: {exc}")

        by_url = {}
        for result in raw_results:
            if result.url:
                by_url.setdefault(result.url.rstrip("/"), result)

        accepted, rejected = [], []
        for result in by_url.values():
            host = _domain(result.url)
            body = f"{result.title}\n{result.content}"
            candidate_dt = self._parse_candidate_datetime(body)
            home_ok = _normal(match["home_team"]) in _normal(body)
            away_ok = _normal(match["away_team"]) in _normal(body)
            pair_ok = self._fixture_pair_ok(body, match["home_team"], match["away_team"])
            competition_ok = self._competition_ok(body, competition)
            date_ok = candidate_dt is not None and candidate_dt.date() == kickoff.date()
            time_ok = candidate_dt is not None and (candidate_dt.hour, candidate_dt.minute) == (kickoff.hour, kickoff.minute)
            official = host in self.official_domains or any(host.endswith("." + d) for d in self.official_domains)
            record = {
                "url": result.url,
                "title": result.title,
                "domain": host,
                "official_domain": official,
                "home_team_match": home_ok,
                "away_team_match": away_ok,
                "home_away_order_match": pair_ok,
                "competition_match": competition_ok,
                "date_match": date_ok,
                "time_match": time_ok,
                "retrieved_at": datetime.now(timezone.utc).isoformat(),
                "snippet": (result.content or "")[:2000],
            }
            if official and home_ok and away_ok and pair_ok and competition_ok and date_ok and time_ok:
                accepted.append(record)
            else:
                rejected.append(record)

        independent_domains = {item["domain"] for item in accepted}
        verified = len(independent_domains) >= 2
        outcome = "RESOLVED" if verified else "UNVERIFIED"
        message = (
            "Ověření úspěšné: dva různé oficiální domény potvrzují oba týmy, jejich pořadí, soutěž, datum a čas."
            if verified else
            "Ověření neúspěšné: nebyly nalezeny dva nezávislé oficiální zdroje potvrzující oba týmy, pořadí, soutěž, datum a přesný čas. Stav zápasu nebyl změněn."
        )
        if search_errors:
            message += " Chyby vyhledávání: " + "; ".join(search_errors)

        with sqlite3.connect(self.db_path, timeout=30) as conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS fixture_verification_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    match_id INTEGER NOT NULL,
                    outcome TEXT NOT NULL,
                    message TEXT NOT NULL,
                    evidence_json TEXT NOT NULL,
                    rejected_json TEXT NOT NULL,
                    verified_at TEXT NOT NULL,
                    FOREIGN KEY(match_id) REFERENCES matches(id)
                )"""
            )
            conn.execute(
                """INSERT INTO fixture_verification_runs
                   (match_id,outcome,message,evidence_json,rejected_json,verified_at)
                   VALUES(?,?,?,?,?,?)""",
                (
                    match_id, outcome, message,
                    json.dumps(accepted, ensure_ascii=False),
                    json.dumps(rejected, ensure_ascii=False),
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            if verified:
                conn.execute(
                    "UPDATE matches SET status='RESOLVED', updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (match_id,),
                )
            conn.commit()

        return {
            "match_id": match_id,
            "outcome": outcome,
            "queries_attempted": len(queries),
            "raw_results_count": len(raw_results),
            "unique_results_count": len(by_url),
            "search_errors": search_errors,
            "message": message,
            "evidence": accepted,
            "rejected_sources": rejected,
        }
