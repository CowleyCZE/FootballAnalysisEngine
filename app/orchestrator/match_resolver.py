import sqlite3
from datetime import datetime
from typing import Optional, Dict, Any
from app.orchestrator.models import AnalysisRequest, MatchIdentity


class MatchResolverException(Exception):
    pass


class AmbiguousMatchException(MatchResolverException):
    pass


class MatchNotFoundException(MatchResolverException):
    pass


class UnverifiedMatchException(MatchResolverException):
    pass


class MatchResolver:
    def __init__(self, db_path: str = "database/football.db"):
        self.db_path = db_path

    def resolve(self, request: AnalysisRequest) -> MatchIdentity:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Query to find match by team names, competition, and scheduled date
        query = """
            SELECT m.id as match_id, m.home_team_id, m.away_team_id, m.competition_id, m.scheduled_at, m.venue, m.status,
                   th.name as home_team, ta.name as away_team, COALESCE(c.name, m.competition, '') as competition
            FROM matches m
            LEFT JOIN teams th ON m.home_team_id = th.id
            LEFT JOIN teams ta ON m.away_team_id = ta.id
            LEFT JOIN competitions c ON m.competition_id = c.id
            WHERE th.name LIKE ? AND ta.name LIKE ? AND (c.name LIKE ? OR m.competition LIKE ? OR m.competition IS NULL OR m.competition = '')
            AND DATE(m.scheduled_at) = DATE(?)
        """

        date_str = request.scheduled_at.strftime("%Y-%m-%d")
        cursor.execute(query, (f"%{request.home_team}%", f"%{request.away_team}%", f"%{request.competition}%", f"%{request.competition}%", date_str))
        rows = cursor.fetchall()
        conn.close()

        if not rows:
            raise MatchNotFoundException(f"Zápas {request.home_team} vs {request.away_team} nebyl v databázi nalezen.")

        if len(rows) > 1:
            raise AmbiguousMatchException(f"Nalezeno více kandidátů ({len(rows)}) pro zápas {request.home_team} vs {request.away_team}.")

        match_data = rows[0]
        scheduled_str = match_data["scheduled_at"]
        scheduled_dt = datetime.fromisoformat(scheduled_str) if isinstance(scheduled_str, str) else scheduled_str

        cutoff_dt = scheduled_dt
        match_status = match_data["status"] if "status" in match_data.keys() and match_data["status"] else "RESOLVED"

        return MatchIdentity(
            match_id=match_data["match_id"],
            home_team_id=match_data["home_team_id"],
            away_team_id=match_data["away_team_id"],
            competition_id=match_data["competition_id"],
            home_team=match_data["home_team"] or request.home_team,
            away_team=match_data["away_team"] or request.away_team,
            competition=match_data["competition"] or request.competition,
            scheduled_at=scheduled_dt,
            data_cutoff_at=cutoff_dt,
            venue=match_data["venue"] if "venue" in match_data.keys() else None,
            status=match_status,
        )

    def resolve_or_create(self, request: AnalysisRequest) -> MatchIdentity:
        try:
            return self.resolve(request)
        except MatchNotFoundException:
            pass

        # Verification: check if both teams exist in authoritative database
        with sqlite3.connect(self.db_path, timeout=30) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            def _get_team(team_name: str) -> Optional[sqlite3.Row]:
                norm_name = team_name.strip().lower()
                return cursor.execute(
                    "SELECT id, name FROM teams WHERE lower(normalized_name) = ? OR lower(name) = ?",
                    (norm_name, norm_name)
                ).fetchone()

            home_team_row = _get_team(request.home_team)
            away_team_row = _get_team(request.away_team)

            # Do NOT create unverified matches automatically
            if not home_team_row or not away_team_row:
                unverified_teams = []
                if not home_team_row:
                    unverified_teams.append(request.home_team)
                if not away_team_row:
                    unverified_teams.append(request.away_team)
                raise MatchNotFoundException(
                    f"Zápas nelze ověřit v autoritativních datech. Neznámé týmy: {', '.join(unverified_teams)}"
                )

            if not request.competition or not request.competition.strip():
                raise MatchNotFoundException("Zápas nelze ověřit: chybí specifikace soutěže.")

            home_team_id = int(home_team_row["id"])
            away_team_id = int(away_team_row["id"])

            scheduled_str = request.scheduled_at.isoformat()
            cursor.execute(
                """
                INSERT INTO matches (home_team_id, away_team_id, competition, scheduled_at, status)
                VALUES (?, ?, ?, ?, 'RESOLVED')
                """,
                (home_team_id, away_team_id, request.competition or "", scheduled_str)
            )
            match_id = int(cursor.lastrowid)
            conn.commit()

        scheduled_dt = request.scheduled_at
        return MatchIdentity(
            match_id=match_id,
            home_team_id=home_team_id,
            away_team_id=away_team_id,
            competition_id=None,
            home_team=home_team_row["name"],
            away_team=away_team_row["name"],
            competition=request.competition,
            scheduled_at=scheduled_dt,
            data_cutoff_at=scheduled_dt,
            venue=None,
            status="RESOLVED",
        )
