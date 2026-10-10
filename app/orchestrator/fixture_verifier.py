"""Evidence-backed fixture verification against search results.

This module deliberately does not mark a match RESOLVED based on search ranking alone.
A candidate must contain both teams, the competition and the exact calendar date, and
must come from an explicitly trusted official domain. Search results are leads; when the
snippet itself is insufficient, the verifier refuses closed and leaves the match unchanged.
"""
from __future__ import annotations

import asyncio
import re
import sqlite3
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from app.search.engine import SearchEngine
from app.search.models import QuerySpec


class FixtureVerificationError(RuntimeError):
    """Raised when available evidence cannot verify one precise fixture."""


# Conservative defaults. Extend this list only with official fixture/schedule domains.
OFFICIAL_SCHEDULE_DOMAINS = {
    "sparta.cz",
    "fotbal.cz",
    "chanceliga.cz",
    "fkpardubice.cz",
}


def _domain(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def _normal(text: str) -> str:
    text = (text or "").casefold()
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
        """Synchronous wrapper for CLI and FastAPI callers."""
        import threading

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.verify(match_id))

        outcome: list[dict[str, Any]] = []
        errors: list[BaseException] = []

        def runner() -> None:
            try:
                outcome.append(asyncio.run(self.verify(match_id)))
            except BaseException as exc:
                errors.append(exc)

        worker = threading.Thread(target=runner, daemon=True)
        worker.start()
        worker.join()
        if errors:
            raise errors[0]
        if not outcome:
            raise FixtureVerificationError("Ověřování skončilo bez výsledku.")
        return outcome[0]

    @staticmethod
    def _local_fixture_datetime(value: str) -> datetime:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            from zoneinfo import ZoneInfo
            dt = dt.replace(tzinfo=ZoneInfo("Europe/Prague"))
        return dt

    @staticmethod
    def _parse_candidate_datetime(text: str) -> datetime | None:
        patterns = [
            r"(?P<day>\d{1,2})[./](?P<month>\d{1,2})[./](?P<year>20\d{2})(?:[ ,T]+(?P<hour>\d{1,2}):(?P<minute>\d{2}))?",
            r"(?P<year>20\d{2})-(?P<month>\d{1,2})-(?P<day>\d{1,2})(?:[ T]+(?P<hour>\d{1,2}):(?P<minute>\d{2}))?",
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if not match:
                continue
            parts = match.groupdict()
            try:
                return datetime(int(parts["year"]), int(parts["month"]), int(parts["day"]), int(parts["hour"] or 0), int(parts["minute"] or 0))
            except ValueError:
                continue
        return None

    @staticmethod
    def _direction_ok(text: str, home: str, away: str) -> bool:
        normalized = _normal(text)
        h, a = _normal(home), _normal(away)
        hpos, apos = normalized.find(h), normalized.find(a)
        if hpos < 0 or apos < 0:
            return False
        if not any(separator in normalized for separator in (" vs ", " v ", " - ", " – ", " at ")):
            return False
        return hpos < apos

    @staticmethod
    def _competition_ok(text: str, competition: str) -> bool:
        name = _normal(competition)
        aliases = {"chance liga": ("chance liga", "1 liga", "ceska chance liga")}
        normalized = _normal(text)
        return any(_normal(alias) in normalized for alias in aliases.get(name, (name,)) if alias)

    @staticmethod
    def _team_ok(text: str, team: str) -> bool:
        return _normal(team) in _normal(text)


    async def verify(self, match_id: int) -> dict[str, Any]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            match = conn.execute(
                """SELECT m.id, m.status, m.scheduled_at, m.competition,
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

        kickoff = self._local_fixture_datetime(match["scheduled_at"])
        competition = match["competition_name"] or ""
        if not competition:
            raise FixtureVerificationError("Zápas nemá určenou soutěž.")

        queries = [
            QuerySpec(
                query=f'"{match["home_team"]}" "{match["away_team"]}" "{competition}" '
                      f'{kickoff.strftime("%Y-%m-%d")} {kickoff.strftime("%d.%m.%Y")} {kickoff.strftime("%H:%M")} official fixture schedule',
                language="en",
                priority=100,
                reason="FIXTURE_VERIFICATION",
            ),
            QuerySpec(
                query=f'"{match["home_team"]}" "{match["away_team"]}" "{competition}" '
                      f'{kickoff.strftime("%d.%m.%Y")} {kickoff.strftime("%H:%M")} rozpis zápasů',
                language="cs",
                priority=100,
                reason="FIXTURE_VERIFICATION",
            ),
        ]
        # Bypass generic identity cutoff filtering: a fixture schedule may not carry
        # publication metadata. Still restrict what can confirm the match below.
        results = []
        for query in queries:
            try:
                raw = await self.search_engine.client.search(
                    query.query, language=query.language, time_range=None
                )
                items = raw if isinstance(raw, list) else raw.get("results", []) if isinstance(raw, dict) else []
                from app.search.normalizer import normalize_searx_result
                results.extend(normalize_searx_result(item) for item in items)
            except Exception:
                continue

        deduped = {}
        for item in results:
            if item.url:
                deduped.setdefault(item.url.rstrip("/"), item)

        evidence = []
        rejected = []
        for result in deduped.values():
            host = _domain(result.url)
            text = f"{result.title}\n{result.content}"
            home_ok = self._team_ok(text, match["home_team"])
            away_ok = self._team_ok(text, match["away_team"])
            team_ok = home_ok and away_ok
            comp_ok = self._competition_ok(text, competition)
            candidate_dt = self._parse_candidate_datetime(text)
            date_ok = candidate_dt is not None and candidate_dt.date() == kickoff.date()
            time_ok = candidate_dt is not None and candidate_dt.hour == kickoff.hour and candidate_dt.minute == kickoff.minute
            direction_ok = self._direction_ok(text, match["home_team"], match["away_team"])
            official = host in self.official_domains or any(host.endswith("." + d) for d in self.official_domains)
            item = {
                "url": result.url,
                "title": result.title,
                "domain": host,
                "official_domain": official,
                "home_team_match": home_ok,
                "away_team_match": away_ok,
                "competition_match": comp_ok,
                "date_match": date_ok,
                "time_match": time_ok,
                "home_away_order_match": direction_ok,
                "retrieved_at": datetime.now(timezone.utc).isoformat(),
                "snippet": (result.content or "")[:2000],
            }
            if official and team_ok and comp_ok and date_ok and time_ok and direction_ok:
                evidence.append(item)
            else:
                rejected.append(item)

        # Two different official domains are required; duplicate URLs from one source
        # cannot satisfy the independence threshold.
        unique_domains = {e["domain"] for e in evidence}
        verified = len(evidence) >= 2 and len(unique_domains) >= 2
        outcome = "RESOLVED" if verified else "UNVERIFIED"
        message = (
            "Ověření úspěšné: nejméně dva nezávislé oficiální zdroje potvrzují oba týmy, pořadí, soutěž, datum a čas."
            if verified else
            "Ověření neúspěšné: systém vyžaduje nejméně dva nezávislé oficiální zdroje potvrzující oba týmy, pořadí, soutěž, datum a čas. Záznam zůstává nezměněn."
        )

        with sqlite3.connect(self.db_path, timeout=30) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS fixture_verification_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    match_id INTEGER NOT NULL,
                    outcome TEXT NOT NULL,
                    message TEXT NOT NULL,
                    evidence_json TEXT NOT NULL,
                    rejected_json TEXT NOT NULL,
                    verified_at TEXT NOT NULL,
                    FOREIGN KEY(match_id) REFERENCES matches(id)
                )
            """)
            import json
            conn.execute(
                """INSERT INTO fixture_verification_runs
                   (match_id,outcome,message,evidence_json,rejected_json,verified_at)
                   VALUES(?,?,?,?,?,?)""",
                (
                    match_id, outcome, message,
                    json.dumps(evidence, ensure_ascii=False),
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
            "message": message,
            "evidence": evidence,
            "rejected_sources": rejected,
        }
