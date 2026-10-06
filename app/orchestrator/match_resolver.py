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


class MatchResolver:
    def __init__(self, db_path: str = "database/football.db"):
        self.db_path = db_path

    def resolve(self, request: AnalysisRequest) -> MatchIdentity:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Dotaz pro dohledání zápasu podle týmu, soutěže a dne
        query = """
            SELECT m.id as match_id, m.home_team_id, m.away_team_id, m.competition_id, m.scheduled_at, m.venue,
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
        )

    def resolve_or_create(self, request: AnalysisRequest) -> MatchIdentity:
        try:
            return self.resolve(request)
        except MatchNotFoundException:
            pass

        # Autonomní zaregistrování nového zápasu a týmů
        with sqlite3.connect(self.db_path, timeout=30) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            def _get_or_create_team(team_name: str) -> int:
                norm_name = team_name.strip().lower()
                row = cursor.execute(
                    "SELECT id FROM teams WHERE lower(normalized_name) = ? OR lower(name) = ?",
                    (norm_name, norm_name)
                ).fetchone()
                if row:
                    return int(row["id"])
                cursor.execute(
                    "INSERT INTO teams (name, normalized_name, competition) VALUES (?, ?, ?)",
                    (team_name, norm_name, request.competition or "")
                )
                return int(cursor.lastrowid)

            home_team_id = _get_or_create_team(request.home_team)
            away_team_id = _get_or_create_team(request.away_team)

            scheduled_str = request.scheduled_at.isoformat()
            cursor.execute(
                """
                INSERT INTO matches (home_team_id, away_team_id, competition, scheduled_at, status)
                VALUES (?, ?, ?, ?, 'SCHEDULED')
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
            home_team=request.home_team,
            away_team=request.away_team,
            competition=request.competition,
            scheduled_at=scheduled_dt,
            data_cutoff_at=scheduled_dt,
            venue=None,
        )
