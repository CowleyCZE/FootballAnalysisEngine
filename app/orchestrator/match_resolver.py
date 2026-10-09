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

        # Query to find match by team names, competition, and scheduled date in authoritative schedule
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
            raise MatchNotFoundException(f"Zápas {request.home_team} vs {request.away_team} pro datum {date_str} nebyl v autoritativním rozpisu nalezen.")

        # If competition was explicitly requested, ensure competition name match or comp_id match in rows
        if request.competition and request.competition.strip():
            req_comp_norm = request.competition.strip().lower()
            filtered_rows = []
            for r in rows:
                c_name = (r["competition"] or "").strip().lower()
                if c_name == req_comp_norm or req_comp_norm in c_name or c_name in req_comp_norm:
                    filtered_rows.append(r)
            rows = filtered_rows

        if not rows:
            raise MatchNotFoundException(f"Zápas {request.home_team} vs {request.away_team} pro soutěž '{request.competition}' a datum {date_str} nebyl v autoritativním rozpisu nalezen.")

        if len(rows) > 1:
            raise AmbiguousMatchException(f"Nalezeno více kandidátů ({len(rows)}) pro zápas {request.home_team} vs {request.away_team}.")

        match_data = rows[0]
        scheduled_str = match_data["scheduled_at"]
        scheduled_dt = datetime.fromisoformat(scheduled_str) if isinstance(scheduled_str, str) else scheduled_str

        cutoff_dt = scheduled_dt
        match_status = match_data["status"] if "status" in match_data.keys() and match_data["status"] else "RESOLVED"

        if match_status == "UNVERIFIED":
            raise UnverifiedMatchException(f"Zápas #{match_data['match_id']} existuje v DB, ale je ve stavu UNVERIFIED (nepotvrzený rozpis). Analýzu nelze spustit.")

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

            if not home_team_row or not away_team_row:
                unverified_reasons = []
                if not home_team_row:
                    unverified_reasons.append(f"domácí tým '{request.home_team}'")
                if not away_team_row:
                    unverified_reasons.append(f"hostující tým '{request.away_team}'")
                if not request.competition or not request.competition.strip():
                    unverified_reasons.append("chybí specifikace soutěže")
                raise MatchNotFoundException(
                    f"Zápas nelze ověřit v autoritativních datech ({', '.join(unverified_reasons)}). Zápas neexistuje v rozpisu."
                )

            # Existence of teams and competition alone DOES NOT verify that a fixture exists.
            # Record request in DB as UNVERIFIED if desired, but NEVER set status = RESOLVED or return a resolved match.
            comp_row = None
            if request.competition:
                comp_norm = request.competition.strip().lower()
                comp_row = cursor.execute("SELECT id, name FROM competitions WHERE lower(name) = ?", (comp_norm,)).fetchone()

            comp_id = int(comp_row["id"]) if comp_row else None
            home_team_id = int(home_team_row["id"])
            away_team_id = int(away_team_row["id"])
            scheduled_str = request.scheduled_at.isoformat()

            cursor.execute(
                """
                INSERT INTO matches (home_team_id, away_team_id, competition_id, competition, scheduled_at, status)
                VALUES (?, ?, ?, ?, ?, 'UNVERIFIED')
                """,
                (home_team_id, away_team_id, comp_id, request.competition or "", scheduled_str)
            )
            match_id = int(cursor.lastrowid)
            conn.commit()

        raise UnverifiedMatchException(
            f"Zápas #{match_id} ({request.home_team} vs {request.away_team}) neexistuje v autoritativním rozpisu pro datum {request.scheduled_at.strftime('%Y-%m-%d')}. "
            f"Existence týmů nebo soutěže v DB nestačí k potvrdit konkrétní utkání. Zápas uložen jako UNVERIFIED a analýza je zablokována."
        )
