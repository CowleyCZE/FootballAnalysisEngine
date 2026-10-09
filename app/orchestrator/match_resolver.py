import sqlite3
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from zoneinfo import ZoneInfo
from app.orchestrator.models import AnalysisRequest, MatchIdentity


class MatchResolverException(Exception):
    pass


class AmbiguousMatchException(MatchResolverException):
    pass


class MatchNotFoundException(MatchResolverException):
    pass


class UnverifiedMatchException(MatchResolverException):
    pass


COMPETITION_ALIASES: Dict[str, str] = {
    "epl": "premier league",
    "english premier league": "premier league",
    "la liga": "la liga",
    "laliga": "la liga",
    "champions league": "uefa champions league",
    "ucl": "uefa champions league",
    "chance liga": "chance liga",
    "czech first league": "chance liga",
}


def normalize_competition_name(name: Optional[str]) -> str:
    if not name or not name.strip():
        return ""
    norm = " ".join(name.strip().lower().split())
    return COMPETITION_ALIASES.get(norm, norm)


def match_competitions(req_comp: str, db_comp: str) -> bool:
    if not req_comp or not req_comp.strip() or not db_comp or not db_comp.strip():
        return False
    return normalize_competition_name(req_comp) == normalize_competition_name(db_comp)


def parse_to_utc(dt_val: Any, default_tz_name: str = "Europe/Prague") -> datetime:
    if isinstance(dt_val, str):
        s = dt_val.strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
    elif isinstance(dt_val, datetime):
        dt = dt_val
    else:
        raise ValueError(f"Cannot parse datetime from {dt_val}")

    if dt.tzinfo is None:
        if not default_tz_name or not str(default_tz_name).strip():
            raise ValueError("Neplatné nebo chybějící název časového pásma.")
        try:
            tz = ZoneInfo(str(default_tz_name).strip())
            dt = dt.replace(tzinfo=tz)
        except Exception as e:
            raise ValueError(f"Neplatné nebo neznámé časové pásmo '{default_tz_name}': {e}")

    return dt.astimezone(timezone.utc)


class MatchResolver:
    def __init__(self, db_path: str = "database/football.db"):
        self.db_path = db_path

    def resolve(self, request: AnalysisRequest) -> MatchIdentity:
        if not request.competition or not request.competition.strip():
            raise UnverifiedMatchException(
                "Požadavek neobsahuje specifikaci soutěže. Zápas nelze potvrdit ani ověřit bez jednoznačně určené soutěže."
            )

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Query candidates by team names
        query = """
            SELECT m.id as match_id, m.home_team_id, m.away_team_id, m.competition_id, m.scheduled_at, m.venue, m.status,
                   th.name as home_team, ta.name as away_team, COALESCE(c.name, m.competition, '') as competition
            FROM matches m
            LEFT JOIN teams th ON m.home_team_id = th.id
            LEFT JOIN teams ta ON m.away_team_id = ta.id
            LEFT JOIN competitions c ON m.competition_id = c.id
            WHERE (th.name LIKE ? OR lower(th.normalized_name) = lower(?))
              AND (ta.name LIKE ? OR lower(ta.normalized_name) = lower(?))
        """

        cursor.execute(
            query,
            (f"%{request.home_team}%", request.home_team, f"%{request.away_team}%", request.away_team)
        )
        candidate_rows = cursor.fetchall()
        conn.close()

        if not candidate_rows:
            raise MatchNotFoundException(f"Zápas {request.home_team} vs {request.away_team} nebyl v autoritativním rozpisu nalezen.")

        req_utc = parse_to_utc(request.scheduled_at, getattr(request, "timezone", "Europe/Prague"))

        filtered_rows = []
        for row in candidate_rows:
            # 1. Strict competition check
            db_comp = row["competition"] or ""
            if request.competition and request.competition.strip():
                if not match_competitions(request.competition, db_comp):
                    continue

            # 2. Kickoff time and timezone check
            if not row["scheduled_at"]:
                continue
            db_utc = parse_to_utc(row["scheduled_at"], getattr(request, "timezone", "Europe/Prague"))

            if req_utc == db_utc:
                filtered_rows.append((row, db_utc))

        if not filtered_rows:
            req_time_str = req_utc.strftime("%Y-%m-%d %H:%M UTC")
            raise MatchNotFoundException(
                f"Zápas {request.home_team} vs {request.away_team} pro soutěž '{request.competition}' "
                f"a čas výkopu {req_time_str} nebyl v autoritativním rozpisu nalezen."
            )

        if len(filtered_rows) > 1:
            raise AmbiguousMatchException(
                f"Nalezeno více kandidátů ({len(filtered_rows)}) pro zápas {request.home_team} vs {request.away_team}."
            )

        match_data, db_utc = filtered_rows[0]

        # Fail-closed status check: ONLY explicit status == 'RESOLVED' is allowed
        match_status = match_data["status"] if ("status" in match_data.keys() and match_data["status"]) else None
        if match_status != "RESOLVED":
            status_str = match_status if match_status else "NULL/EMPTY"
            raise UnverifiedMatchException(
                f"Zápas #{match_data['match_id']} existuje v DB, ale je ve stavu '{status_str}' "
                f"(pouze explicitní stav RESOLVED je povolen pro spuštění analýzy)."
            )

        return MatchIdentity(
            match_id=match_data["match_id"],
            home_team_id=match_data["home_team_id"],
            away_team_id=match_data["away_team_id"],
            competition_id=match_data["competition_id"],
            home_team=match_data["home_team"] or request.home_team,
            away_team=match_data["away_team"] or request.away_team,
            competition=match_data["competition"] or request.competition,
            scheduled_at=db_utc,
            data_cutoff_at=db_utc,
            venue=match_data["venue"] if "venue" in match_data.keys() else None,
            status=match_status,
        )

    def resolve_or_create(self, request: AnalysisRequest) -> MatchIdentity:
        if not request.competition or not request.competition.strip():
            raise UnverifiedMatchException(
                "Požadavek neobsahuje specifikaci soutěže. Zápas nelze potvrdit ani ověřit bez jednoznačně určené soutěže."
            )

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
