from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Any, Iterable

REQUIRED_FIELDS = (
    "external_match_id",
    "home_team",
    "away_team",
    "scheduled_at",
    "status",
)


def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _normalized_team_name(name: str) -> str:
    return _clean_text(name).casefold()


def _parse_date(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def validate_match_record(record: dict[str, Any], *, now: datetime | None = None) -> list[str]:
    """Vrátí seznam chyb; prázdný seznam znamená bezpečně importovatelný záznam."""
    errors: list[str] = []
    now = now or datetime.now(timezone.utc)

    for field in REQUIRED_FIELDS:
        if not _clean_text(record.get(field)):
            errors.append(f"missing field: {field}")

    external_id = _clean_text(record.get("external_match_id"))
    if external_id and len(external_id) > 255:
        errors.append("external_match_id is too long")

    home = _clean_text(record.get("home_team"))
    away = _clean_text(record.get("away_team"))
    if home and home.casefold() == away.casefold():
        errors.append("home and away team are identical")

    scheduled_at = _clean_text(record.get("scheduled_at"))
    kickoff = _parse_date(scheduled_at)
    if scheduled_at and kickoff is None:
        errors.append("invalid scheduled_at timestamp")

    status = _clean_text(record.get("status")).upper()
    if status not in {"FINISHED", "SCHEDULED", "POSTPONED", "CANCELLED"}:
        errors.append(f"unsupported status: {status or '<empty>'}")

    goals: list[int | None] = []
    for field in ("home_goals", "away_goals"):
        value = record.get(field)
        if value in (None, ""):
            goals.append(None)
            continue
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            errors.append(f"invalid {field}")
            goals.append(None)
            continue
        if parsed < 0:
            errors.append(f"negative {field}")
        goals.append(parsed)

    if status == "FINISHED" and (goals[0] is None or goals[1] is None):
        errors.append("finished match requires both final scores")

    if status == "FINISHED" and kickoff and kickoff > now:
        errors.append("finished match has a future kickoff time")

    for field in ("home_xg", "away_xg", "home_xga", "away_xga"):
        value = record.get(field)
        if value in (None, ""):
            continue
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            errors.append(f"invalid {field}")
            continue
        if parsed < 0:
            errors.append(f"negative {field}")

    return errors


def _get_or_create_team(conn: sqlite3.Connection, name: str, competition: str) -> int:
    normalized = _normalized_team_name(name)
    row = conn.execute(
        "SELECT id FROM teams WHERE normalized_name = ?",
        (normalized,),
    ).fetchone()
    if row:
        return int(row[0])

    cursor = conn.execute(
        """
        INSERT INTO teams (name, normalized_name, competition)
        VALUES (?, ?, ?)
        """,
        (_clean_text(name), normalized, _clean_text(competition)),
    )
    return int(cursor.lastrowid)


def _get_or_create_match(
    conn: sqlite3.Connection,
    record: dict[str, Any],
    home_team_id: int,
    away_team_id: int,
) -> int:
    external_id = _clean_text(record["external_match_id"])
    row = conn.execute(
        "SELECT id FROM matches WHERE external_match_id = ?",
        (external_id,),
    ).fetchone()
    if row:
        return int(row[0])

    cursor = conn.execute(
        """
        INSERT INTO matches (
            external_match_id, competition, season, home_team_id, away_team_id,
            scheduled_at, kickoff_time_known, status
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            external_id,
            _clean_text(record.get("competition", "Chance Liga")),
            _clean_text(record.get("season")) or None,
            home_team_id,
            away_team_id,
            _clean_text(record["scheduled_at"]),
            1 if _clean_text(record.get("kickoff_time_known", "1")).lower() in {"1", "true", "yes"} else 0,
            _clean_text(record["status"]).upper(),
        ),
    )
    return int(cursor.lastrowid)


def _upsert_match_statistics(conn: sqlite3.Connection, match_id: int, record: dict[str, Any]) -> None:
    def optional_int(field: str) -> int | None:
        value = record.get(field)
        return None if value in (None, "") else int(value)

    def optional_float(field: str) -> float | None:
        value = record.get(field)
        return None if value in (None, "") else float(value)

    conn.execute(
        """
        INSERT INTO match_statistics (
            match_id, home_goals, away_goals, home_xg, away_xg, home_xga, away_xga
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(match_id) DO UPDATE SET
            home_goals = excluded.home_goals,
            away_goals = excluded.away_goals,
            home_xg = excluded.home_xg,
            away_xg = excluded.away_xg,
            home_xga = excluded.home_xga,
            away_xga = excluded.away_xga,
            updated_at = CURRENT_TIMESTAMP
        """,
        (
            match_id,
            optional_int("home_goals"),
            optional_int("away_goals"),
            optional_float("home_xg"),
            optional_float("away_xg"),
            optional_float("home_xga"),
            optional_float("away_xga"),
        ),
    )


def import_history_records(
    conn: sqlite3.Connection,
    records: Iterable[dict[str, Any]],
    *,
    competition: str = "Chance Liga",
    season: str | None = None,
    now: datetime | None = None,
) -> dict[str, int]:
    """Importuje historické zápasy idempotentně podle external_match_id.

    Nevalidní záznamy se neimportují. Chybějící xG není chyba: model musí
    později pracovat se stavem nedostatečných dat, nikdy s vymyšlenou hodnotou.
    """
    imported = 0
    updated = 0
    skipped = 0

    for raw_record in records:
        record = dict(raw_record)
        record.setdefault("competition", competition)
        if season and not record.get("season"):
            record["season"] = season

        errors = validate_match_record(record, now=now)
        if errors:
            skipped += 1
            continue

        home_team_id = _get_or_create_team(conn, record["home_team"], record["competition"])
        away_team_id = _get_or_create_team(conn, record["away_team"], record["competition"])

        existing = conn.execute(
            "SELECT id FROM matches WHERE external_match_id = ?",
            (_clean_text(record["external_match_id"]),),
        ).fetchone()
        match_id = _get_or_create_match(conn, record, home_team_id, away_team_id)
        if existing:
            updated += 1
        else:
            imported += 1

        _upsert_match_statistics(conn, match_id, record)

    conn.commit()
    return {"imported": imported, "updated": updated, "skipped": skipped}


def audit_history_import(
    conn: sqlite3.Connection,
    *,
    competition: str = "Chance Liga",
    now: datetime | None = None,
) -> dict[str, int]:
    """Spustí kontrolní dotazy po importu historických dat."""
    now = now or datetime.now(timezone.utc)
    now_text = now.isoformat()

    total = conn.execute(
        "SELECT COUNT(*) FROM matches WHERE competition = ?",
        (competition,),
    ).fetchone()[0]

    duplicates = conn.execute(
        """
        SELECT COUNT(*)
        FROM (
            SELECT external_match_id
            FROM matches
            WHERE competition = ? AND external_match_id IS NOT NULL
            GROUP BY external_match_id
            HAVING COUNT(*) > 1
        )
        """,
        (competition,),
    ).fetchone()[0]

    finished_without_result = conn.execute(
        """
        SELECT COUNT(*)
        FROM matches m
        LEFT JOIN match_statistics s ON s.match_id = m.id
        WHERE m.competition = ?
          AND m.status = 'FINISHED'
          AND (s.home_goals IS NULL OR s.away_goals IS NULL)
        """,
        (competition,),
    ).fetchone()[0]

    future_finished = conn.execute(
        """
        SELECT COUNT(*)
        FROM matches
        WHERE competition = ?
          AND status = 'FINISHED'
          AND scheduled_at > ?
        """,
        (competition, now_text),
    ).fetchone()[0]

    missing_xg = conn.execute(
        """
        SELECT COUNT(*)
        FROM matches m
        LEFT JOIN match_statistics s ON s.match_id = m.id
        WHERE m.competition = ?
          AND m.status = 'FINISHED'
          AND (s.home_xg IS NULL OR s.away_xg IS NULL)
        """,
        (competition,),
    ).fetchone()[0]

    return {
        "total_matches": int(total),
        "duplicate_external_ids": int(duplicates),
        "finished_without_result": int(finished_without_result),
        "future_finished_matches": int(future_finished),
        "finished_matches_missing_xg": int(missing_xg),
    }
