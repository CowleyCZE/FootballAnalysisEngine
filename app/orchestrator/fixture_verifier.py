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

from app.orchestrator.match_resolver import parse_to_utc
from app.search.engine import SearchEngine
from app.search.models import QuerySpec
from app.search.searxng_client import SearXNGClient


class FixtureVerificationError(RuntimeError):
    """Raised when available evidence cannot verify one precise fixture."""


# Conservative defaults. Extend this list only with official fixture/schedule domains.
OFFICIAL_SCHEDULE_DOMAINS = {
    "sparta.cz",
    "fotbal.cz",
    "ligafotbal.cz",
    "chanceliga.cz",
    "www.chanceliga.cz",
}


def _domain(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def _normal(text: str) -> str:
    text = (text or "").casefold()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def _has_team(text: str, name: str) -> bool:
    normalized_text = _normal(text)
    normalized_name = _normal(name)
    if not normalized_name:
        return False
    if normalized_name in normalized_text:
        return True
    # Permit a shortened name only where a distinctive token (>3 chars) is present.
    tokens = [t for t in normalized_name.split() if len(t) > 3 and t not in {"football", "club"}]
    return bool(tokens) and all(t in normalized_text for t in tokens)


def _has_date(text: str, kickoff: datetime) -> bool:
    local = kickoff.date()
    candidates = {
        kickoff.strftime("%Y-%m-%d"),
        kickoff.strftime("%d.%m.%Y"),
        kickoff.strftime("%d/%m/%Y"),
        kickoff.strftime("%d.%m.%y"),
        kickoff.strftime("%d/%m"),
        kickoff.strftime("%d/%m").lstrip("0"),
        kickoff.strftime("%B %d, %Y"),
        kickoff.strftime("%d %B %Y"),
    }
    return any(c and c.casefold() in (text or "").casefold() for c in candidates)


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

        kickoff = parse_to_utc(match["scheduled_at"])
        competition = match["competition_name"] or ""
        if not competition:
            raise FixtureVerificationError("Zápas nemá určenou soutěž.")

        queries = [
            QuerySpec(
                query=f'"{match["home_team"]}" "{match["away_team"]}" "{competition}" '
                      f'{kickoff.strftime("%Y-%m-%d")} official fixture schedule',
                language="en",
                priority=100,
                reason="FIXTURE_VERIFICATION",
            ),
            QuerySpec(
                query=f'"{match["home_team"]}" "{match["away_team"]}" "{competition}" '
                      f'{kickoff.strftime("%d.%m.%Y")} rozpis zápasů',
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
            team_ok = _has_team(text, match["home_team"]) and _has_team(text, match["away_team"])
            comp_ok = _has_team(text, competition)
            date_ok = _has_date(text, kickoff)
            official = host in self.official_domains or any(host.endswith("." + d) for d in self.official_domains)
            item = {
                "url": result.url,
                "title": result.title,
                "domain": host,
                "official_domain": official,
                "home_team_match": _has_team(text, match["home_team"]),
                "away_team_match": _has_team(text, match["away_team"]),
                "competition_match": comp_ok,
                "date_match": date_ok,
                "retrieved_at": datetime.now(timezone.utc).isoformat(),
                "snippet": (result.content or "")[:2000],
            }
            if official and team_ok and comp_ok and date_ok:
                evidence.append(item)
            else:
                rejected.append(item)

        # A single source can be a direct official schedule. If the search provider
        # gives no explicit match/date snippet, we do not promote the record.
        unique_domains = {e["domain"] for e in evidence}
        verified = len(evidence) >= 1 and len(unique_domains) >= 1
        outcome = "RESOLVED" if verified else "UNVERIFIED"
        message = (
            "Ověření úspěšné: nalezen oficiální zdroj s oběma týmy, soutěží a přesným datem."
            if verified else
            "Ověření neúspěšné: nebyl nalezen oficiální výsledek obsahující oba týmy, soutěž a přesné datum. Záznam zůstává nezměněn."
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
