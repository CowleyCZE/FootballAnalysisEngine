"""Canonical team identity helpers and the one-time legacy ID consolidation."""
from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from typing import Any

from app.statistics.history_autofill import canonical_team_key, resolve_team_key


def register_alias(conn: sqlite3.Connection, team_id: int, alias: str, source: str = "import") -> None:
    alias = str(alias or "").strip()
    normalized = canonical_team_key(alias)
    if not alias or not normalized:
        return
    conn.execute("""INSERT OR IGNORE INTO team_aliases(alias_name,normalized_alias,team_id,source)
        VALUES(?,?,?,?)""", (alias, normalized, int(team_id), source))


def find_team_id(conn: sqlite3.Connection, name: str) -> int | None:
    """Resolve a known team spelling without creating an unverified team."""
    display = str(name or "").strip()
    key = resolve_team_key(display)
    if not key:
        return None
    row = conn.execute("SELECT id FROM teams WHERE normalized_name=?", (key,)).fetchone()
    if not row:
        raw_key = canonical_team_key(display)
        row = conn.execute("SELECT team_id FROM team_aliases WHERE normalized_alias=? ORDER BY team_id LIMIT 1", (raw_key,)).fetchone()
    if not row:
        for ident, existing in conn.execute("SELECT id,name FROM teams").fetchall():
            if resolve_team_key(existing) == key:
                row = (ident,)
                break
    if row:
        team_id = int(row[0])
        register_alias(conn, team_id, display)
        return team_id


def get_or_create_team(conn: sqlite3.Connection, name: str, competition: str | None = None) -> int:
    """Resolve every known spelling to one canonical teams.id."""
    display = str(name or "").strip()
    if not display:
        raise ValueError("Název týmu nesmí být prázdný.")
    team_id = find_team_id(conn, display)
    if team_id is not None:
        return team_id
    key = resolve_team_key(display)
    cursor = conn.execute("INSERT INTO teams(name,normalized_name,competition) VALUES(?,?,?)",
                          (display, key, competition))
    team_id = int(cursor.lastrowid)
    register_alias(conn, team_id, display)
    return team_id


def _merge_json_rows(rows: list[sqlite3.Row], json_column: str, *, list_keys: tuple[str, ...] = ()) -> str:
    merged: dict[str, Any] = {}
    lists: dict[str, list] = defaultdict(list)
    for row in rows:
        try:
            payload = json.loads(row[json_column] or "{}")
        except (TypeError, ValueError):
            continue
        if not isinstance(payload, dict):
            continue
        for key, value in payload.items():
            if key in list_keys and isinstance(value, list):
                for item in value:
                    if item not in lists[key]:
                        lists[key].append(item)
            elif value is not None and (key not in merged or merged[key] is None):
                merged[key] = value
    merged.update(lists)
    return json.dumps(merged, ensure_ascii=False, sort_keys=True)


def _consolidate_unique_table(conn: sqlite3.Connection, table: str, team_map: dict[int, int],
                              group_columns: tuple[str, ...], json_column: str | None = None,
                              list_keys: tuple[str, ...] = ()) -> None:
    rows = conn.execute(f"SELECT * FROM {table}").fetchall()
    groups: dict[tuple, list[sqlite3.Row]] = defaultdict(list)
    for row in rows:
        values = []
        for column in group_columns:
            value = row[column]
            if column == "team_id" and value is not None:
                value = team_map.get(int(value), int(value))
            elif column in {"home_team_id", "away_team_id"} and value is not None:
                value = team_map.get(int(value), int(value))
            values.append(value)
        groups[tuple(values)].append(row)
    for key, group in groups.items():
        remapped = any(
            int(row[column]) in team_map and team_map[int(row[column])] != int(row[column])
            for row in group for column in ("team_id", "home_team_id", "away_team_id")
            if column in row.keys() and row[column] is not None
        )
        if len(group) < 2 or not remapped:
            for row in group:
                for column in group_columns:
                    if column in {"team_id", "home_team_id", "away_team_id"} and row[column] is not None:
                        target = team_map.get(int(row[column]), int(row[column]))
                        if target != int(row[column]):
                            conn.execute(f"UPDATE {table} SET {column}=? WHERE id=?", (target, int(row["id"])))
            continue
        keeper = max(group, key=lambda r: (str(r["created_at"] if "created_at" in r.keys() else r["updated_at"] or ""), int(r["id"])))
        if json_column:
            merged = _merge_json_rows(group, json_column, list_keys=list_keys)
            conn.execute(f"UPDATE {table} SET {json_column}=? WHERE id=?", (merged, int(keeper["id"])))
        for row in group:
            if int(row["id"]) != int(keeper["id"]):
                conn.execute(f"DELETE FROM {table} WHERE id=?", (int(row["id"]),))
        for column, value in zip(group_columns, key):
            if column in {"team_id", "home_team_id", "away_team_id"} and value is not None:
                conn.execute(f"UPDATE {table} SET {column}=? WHERE id=?", (int(value), int(keeper["id"])))


def consolidate_legacy_team_ids(conn: sqlite3.Connection) -> dict[str, int]:
    """Merge rows that resolve to the same alias key and remap all team FKs."""
    conn.row_factory = sqlite3.Row
    # Opakovatelné (TODO 11.28): menu dříve zakládalo týmy bez aliasů („Zlín“ vedle „FC FASTAV Zlin“), takže se
    # jednorázový marker nesmí používat k přeskočení. Slučuje se jen tehdy, když duplicity skutečně existují.
    raw = conn.execute("SELECT id,name FROM teams ORDER BY id").fetchall()
    groups: dict[str, list[tuple[int, str]]] = defaultdict(list)
    for ident, name in ((r[0], r[1]) for r in raw):
        key = resolve_team_key(str(name)) or canonical_team_key(str(name))
        groups[key].append((int(ident), str(name)))
    if all(len(members) < 2 for members in groups.values()):
        return {"merged": 0, "teams": len(raw)}

    team_map: dict[int, int] = {}
    aliases: list[tuple[int, str]] = []
    for key, members in groups.items():
        if not key:
            continue
        def reference_score(member: tuple[int, str]) -> tuple[int, int]:
            ident = member[0]
            count = int(conn.execute("SELECT COUNT(*) FROM matches WHERE home_team_id=? OR away_team_id=?", (ident, ident)).fetchone()[0])
            count += int(conn.execute("SELECT COUNT(*) FROM team_season_snapshots WHERE team_id=?", (ident,)).fetchone()[0])
            return count, -ident
        keeper = max(members, key=reference_score)[0]
        for ident, name in members:
            team_map[ident] = keeper
            aliases.append((keeper, name))

    duplicate_ids = {old: new for old, new in team_map.items() if old != new}
    if duplicate_ids:
        # Collapse rows whose declared unique keys become equal after ID remapping.
        _consolidate_unique_table(conn, "team_season_snapshots", team_map,
                                  ("team_id", "competition", "season", "data_cutoff_at", "source_file"),
                                  "metrics_json")
        _consolidate_unique_table(conn, "match_xg_observations", team_map,
                                  ("match_date", "home_team_id", "away_team_id", "source_file"))
        _consolidate_unique_table(conn, "statistical_snapshots", team_map,
                                  ("run_id", "team_id", "metric", "data_cutoff_at", "calculation_version"))
        _consolidate_unique_table(conn, "team_profile_snapshots", team_map,
                                  ("team_id", "data_cutoff_at", "source_run_id"), "profile_json",
                                  ("facts", "head_to_head_facts"))
        for table, columns in (("players", ("team_id",)), ("matches", ("home_team_id", "away_team_id"))):
            for column in columns:
                for old, new in duplicate_ids.items():
                    conn.execute(f"UPDATE {table} SET {column}=? WHERE {column}=?", (new, old))
        for old, new in duplicate_ids.items():
            old_stadium = conn.execute("SELECT * FROM team_stadiums WHERE team_id=?", (old,)).fetchone()
            if not old_stadium:
                continue
            new_stadium = conn.execute("SELECT * FROM team_stadiums WHERE team_id=?", (new,)).fetchone()
            if not new_stadium:
                conn.execute("UPDATE team_stadiums SET team_id=? WHERE team_id=?", (new, old))
            else:
                columns = [row[1] for row in conn.execute("PRAGMA table_info(team_stadiums)") if row[1] != "team_id"]
                assignments = ",".join(f'"{column}"=COALESCE("{column}",?)' for column in columns)
                conn.execute(f"UPDATE team_stadiums SET {assignments} WHERE team_id=?",
                             tuple(old_stadium[column] for column in columns) + (new,))
                conn.execute("DELETE FROM team_stadiums WHERE team_id=?", (old,))
        for old in duplicate_ids:
            conn.execute("DELETE FROM team_aliases WHERE team_id=?", (old,))
        for old in duplicate_ids:
            conn.execute("DELETE FROM teams WHERE id=?", (old,))

    # Canonical normalized names are unique and are used by every new importer.
    for key, members in groups.items():
        if not key:
            continue
        keeper = team_map[members[0][0]]
        conn.execute("UPDATE teams SET normalized_name=?,updated_at=CURRENT_TIMESTAMP WHERE id=?", (key, keeper))
    for team_id, alias in aliases:
        register_alias(conn, team_id, alias, "legacy-deduplication")
    conn.execute("INSERT OR REPLACE INTO system_info(key,value) VALUES('team_identity_migration_v2','done')")
    remaining = int(conn.execute("SELECT COUNT(*) FROM teams").fetchone()[0])
    return {"merged": len(duplicate_ids), "teams": remaining}


def consolidate_duplicate_matches(conn: sqlite3.Connection) -> dict[str, int]:
    """Collapse duplicate fixture rows only when their stats agree and no other rows are orphaned."""
    conn.row_factory = sqlite3.Row
    groups = conn.execute("""SELECT home_team_id,away_team_id,COALESCE(competition_id,-1),
        lower(trim(COALESCE(competition,''))),substr(scheduled_at,1,10),group_concat(id)
        FROM matches WHERE home_team_id IS NOT NULL AND away_team_id IS NOT NULL AND scheduled_at IS NOT NULL
        GROUP BY home_team_id,away_team_id,COALESCE(competition_id,-1),
        lower(trim(COALESCE(competition,''))),substr(scheduled_at,1,10) HAVING COUNT(*)>1""").fetchall()
    merged = skipped = 0
    for group in groups:
        ids = [int(value) for value in str(group[5]).split(",")]
        marks = ",".join("?" for _ in ids)
        matches = conn.execute(f"SELECT * FROM matches WHERE id IN ({marks})", ids).fetchall()
        stats = {int(row["match_id"]): row for row in conn.execute(
            f"SELECT * FROM match_statistics WHERE match_id IN ({marks})", ids).fetchall()}
        stat_columns = [row[1] for row in conn.execute("PRAGMA table_info(match_statistics)")
                        if row[1] not in {"id", "match_id", "created_at", "updated_at", "xg_metric_definition"}]
        # Keep a source-confirmed kickoff and external identity when available.
        keeper = max(matches, key=lambda row: (int(row["kickoff_time_known"] or 0),
                     int(bool(row["external_match_id"])), int(row["status"] == "RESOLVED"),
                     str(row["updated_at"] or ""), -int(row["id"])))
        keeper_id = int(keeper["id"])
        all_refs = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        safe = True
        for (table,) in all_refs:
            if table in {"matches", "match_statistics"}:
                continue
            columns = {row[1] for row in conn.execute(f'PRAGMA table_info("{table}")')}
            if "match_id" in columns and conn.execute(
                f'SELECT 1 FROM "{table}" WHERE match_id IN ({marks}) LIMIT 1', ids).fetchone():
                safe = False
                break
        merged_stats: dict[str, Any] = {}
        for column in stat_columns:
            values = {row[column] for row in stats.values() if row[column] is not None}
            if len(values) > 1:
                safe = False
                break
            merged_stats[column] = next(iter(values)) if values else None
        merged_definition = next((row["xg_metric_definition"] for row in (stats.get(keeper_id), *stats.values())
                                  if row and row["xg_metric_definition"]), None)
        external_ids = {row["external_match_id"] for row in matches if row["external_match_id"]}
        known_times = {row["scheduled_at"] for row in matches if row["kickoff_time_known"]}
        if len(external_ids) > 1 or len(known_times) > 1:
            safe = False
        if not safe:
            skipped += 1
            continue
        external_id = next(iter(external_ids)) if external_ids else None
        known_time = next(iter(known_times)) if known_times else None
        venue = next((row["venue"] for row in matches if row["venue"]), None)
        source = next((row["kickoff_time_source"] for row in matches if row["kickoff_time_known"] and row["kickoff_time_source"]), None)
        status = "RESOLVED" if any(row["status"] == "RESOLVED" for row in matches) else keeper["status"]
        conn.execute("""UPDATE matches SET external_match_id=COALESCE(external_match_id,?),
            scheduled_at=COALESCE(?,scheduled_at),kickoff_time_known=MAX(kickoff_time_known,?),
            kickoff_time_source=COALESCE(kickoff_time_source,?),venue=COALESCE(venue,?),status=?,
            updated_at=CURRENT_TIMESTAMP WHERE id=?""",
            (external_id, known_time, int(bool(known_time)), source, venue, status, keeper_id))
        keeper_stats = stats.get(keeper_id)
        if keeper_stats:
            assignments = ",".join(f'"{column}"=?' for column in stat_columns)
            conn.execute(f"UPDATE match_statistics SET {assignments},xg_metric_definition=COALESCE(xg_metric_definition,?),updated_at=CURRENT_TIMESTAMP WHERE match_id=?",
                         tuple(merged_stats[column] for column in stat_columns) + (merged_definition, keeper_id))
        elif stats:
            old_stat_id = next(iter(stats))
            conn.execute("UPDATE match_statistics SET match_id=? WHERE match_id=?", (keeper_id, old_stat_id))
            keeper_stats = stats[old_stat_id]
        for match_id in ids:
            if match_id == keeper_id:
                continue
            if match_id in stats and int(stats[match_id]["id"]) != int(keeper_stats["id"]):
                conn.execute("DELETE FROM match_statistics WHERE match_id=?", (match_id,))
            conn.execute("DELETE FROM matches WHERE id=?", (match_id,))
        merged += len(ids) - 1
    return {"merged": merged, "skipped_groups": skipped}
