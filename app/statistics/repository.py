import sqlite3
import json
from typing import List, Dict, Any, Optional
from app.statistics.models import MatchStatistics
from app.database.schema import initialize_database

class StatisticsRepository:
    def __init__(self, db_path: str = "database/football.db"):
        self.db_path = db_path
        initialize_database(self.db_path)

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def save_match_statistics(self, stats: MatchStatistics) -> bool:
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("""
                INSERT INTO match_statistics (
                    match_id, home_goals, away_goals, home_ht_goals, away_ht_goals,
                    home_ft_goals, away_ft_goals, home_shots, away_shots,
                    home_shots_on_target, away_shots_on_target, home_possession, away_possession,
                    home_corners, away_corners, home_yellow_cards, away_yellow_cards,
                    home_red_cards, away_red_cards, home_xg, away_xg, home_xga, away_xga,
                    home_npxg, away_npxg, home_gs_adj_xg, away_gs_adj_xg, xg_metric_definition
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(match_id) DO UPDATE SET
                    home_goals=excluded.home_goals, away_goals=excluded.away_goals,
                    home_npxg=COALESCE(excluded.home_npxg, match_statistics.home_npxg),
                    away_npxg=COALESCE(excluded.away_npxg, match_statistics.away_npxg),
                    home_gs_adj_xg=COALESCE(excluded.home_gs_adj_xg, match_statistics.home_gs_adj_xg),
                    away_gs_adj_xg=COALESCE(excluded.away_gs_adj_xg, match_statistics.away_gs_adj_xg),
                    home_xg=COALESCE(excluded.home_xg, match_statistics.home_xg),
                    away_xg=COALESCE(excluded.away_xg, match_statistics.away_xg),
                    home_xga=COALESCE(excluded.home_xga, match_statistics.home_xga),
                    away_xga=COALESCE(excluded.away_xga, match_statistics.away_xga),
                    xg_metric_definition=COALESCE(excluded.xg_metric_definition, match_statistics.xg_metric_definition),
                    home_shots=excluded.home_shots, away_shots=excluded.away_shots,
                    home_shots_on_target=excluded.home_shots_on_target, away_shots_on_target=excluded.away_shots_on_target,
                    home_possession=excluded.home_possession, away_possession=excluded.away_possession,
                    updated_at=CURRENT_TIMESTAMP
            """, (
                stats.match_id, stats.home_goals, stats.away_goals, stats.home_ht_goals, stats.away_ht_goals,
                stats.home_ft_goals, stats.away_ft_goals, stats.home_shots, stats.away_shots,
                stats.home_shots_on_target, stats.away_shots_on_target, stats.home_possession, stats.away_possession,
                stats.home_corners, stats.away_corners, stats.home_yellow_cards, stats.away_yellow_cards,
                stats.home_red_cards, stats.away_red_cards, stats.home_xg, stats.away_xg, stats.home_xga, stats.away_xga,
                stats.home_npxg, stats.away_npxg, stats.home_gs_adj_xg, stats.away_gs_adj_xg,
                stats.xg_metric_definition
            ))
            conn.commit()
            return True
        finally:
            conn.close()

    def get_match_statistics(self, match_id: int) -> Optional[Dict[str, Any]]:
        conn = self._get_connection()
        try:
            row = conn.execute("SELECT * FROM match_statistics WHERE match_id = ?", (match_id,)).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def get_match_kickoff(self, match_id: int) -> Optional[str]:
        conn = self._get_connection()
        try:
            row = conn.execute("SELECT scheduled_at FROM matches WHERE id = ?", (match_id,)).fetchone()
            return row["scheduled_at"] if row and row["scheduled_at"] else None
        finally:
            conn.close()

    def get_league_goal_stats(self, match_id: int, cutoff_datetime: str) -> Dict[str, Any]:
        """Průměr gólů na tým a zápas ze všech odehraných zápasů soutěže cílového zápasu.

        Jen zápasy s výsledkem, ≤ cutoff a před výkopem cílového zápasu (cílový zápas se nepočítá).
        """
        conn = self._get_connection()
        try:
            target = conn.execute(
                "SELECT competition_id, competition, scheduled_at FROM matches WHERE id = ?", (match_id,)
            ).fetchone()
            if not target:
                return {"matches": 0, "mean": None}
            if target["competition_id"] is not None:
                comp_sql, comp_param = "m.competition_id = ?", target["competition_id"]
            elif target["competition"] and str(target["competition"]).strip():
                comp_sql, comp_param = "m.competition = ?", target["competition"]
            else:
                return {"matches": 0, "mean": None}

            sql = (
                "SELECT COUNT(*) AS n, SUM(ms.home_goals + ms.away_goals) AS goals "
                "FROM matches m JOIN match_statistics ms ON ms.match_id = m.id "
                f"WHERE {comp_sql} AND m.id != ? "
                "AND ms.home_goals IS NOT NULL AND ms.away_goals IS NOT NULL "
                "AND julianday(m.scheduled_at) <= julianday(?)"
            )
            params: List[Any] = [comp_param, match_id, cutoff_datetime]
            if target["scheduled_at"]:
                sql += " AND julianday(m.scheduled_at) < julianday(?)"
                params.append(target["scheduled_at"])
            row = conn.execute(sql, params).fetchone()
            n = int(row["n"] or 0)
            if n == 0:
                return {"matches": 0, "mean": None}
            return {"matches": n, "mean": float(row["goals"]) / (2.0 * n)}
        finally:
            conn.close()

    def get_league_matches(self, match_id: int, cutoff_datetime: str, limit: int = 2000) -> List[Dict[str, Any]]:
        """Odehrané zápasy soutěže cílového zápasu (≤ cutoff, před výkopem, bez cílového zápasu).

        Slouží k odhadu síly soupeřů; vrací jen týmy a góly.
        """
        conn = self._get_connection()
        try:
            target = conn.execute(
                "SELECT competition_id, competition, scheduled_at FROM matches WHERE id = ?", (match_id,)
            ).fetchone()
            if not target:
                return []
            if target["competition_id"] is not None:
                comp_sql, comp_param = "m.competition_id = ?", target["competition_id"]
            elif target["competition"] and str(target["competition"]).strip():
                comp_sql, comp_param = "m.competition = ?", target["competition"]
            else:
                return []
            sql = (
                "SELECT m.id AS match_id, m.home_team_id, m.away_team_id, m.scheduled_at, ms.home_goals, ms.away_goals, "
                "ms.home_xg, ms.away_xg, ms.home_npxg, ms.away_npxg, ms.home_gs_adj_xg, ms.away_gs_adj_xg "
                "FROM matches m JOIN match_statistics ms ON ms.match_id = m.id "
                f"WHERE {comp_sql} AND m.id != ? "
                "AND ms.home_goals IS NOT NULL AND ms.away_goals IS NOT NULL "
                "AND julianday(m.scheduled_at) <= julianday(?)"
            )
            params: List[Any] = [comp_param, match_id, cutoff_datetime]
            if target["scheduled_at"]:
                sql += " AND julianday(m.scheduled_at) < julianday(?)"
                params.append(target["scheduled_at"])
            sql += " ORDER BY m.scheduled_at DESC LIMIT ?"
            params.append(limit)
            return [dict(r) for r in conn.execute(sql, params).fetchall()]
        finally:
            conn.close()

    def get_league_xg_observations(self, match_id: int, cutoff_datetime: str,
                                   before_kickoff: Optional[str] = None, limit: int = 4000) -> List[Dict[str, Any]]:
        """Dated xG observations for the target competition, strictly before cutoff/kickoff."""
        conn = self._get_connection()
        try:
            target = conn.execute(
                "SELECT competition_id, competition, scheduled_at FROM matches WHERE id=?", (match_id,)
            ).fetchone()
            if not target:
                return []
            if target["competition_id"] is not None:
                comp_sql, comp_value = "o.competition = COALESCE((SELECT name FROM competitions WHERE id=?), o.competition)", target["competition_id"]
            elif target["competition"]:
                comp_sql, comp_value = "o.competition = ?", target["competition"]
            else:
                return []
            sql = ("SELECT o.match_date AS scheduled_at, o.home_team_id, o.away_team_id, "
                   "o.home_xg, o.away_xg, o.home_npxg, o.away_npxg, "
                   "o.home_gs_adj_xg, o.away_gs_adj_xg FROM match_xg_observations o "
                   f"WHERE {comp_sql} AND julianday(o.match_date) <= julianday(?)")
            params: List[Any] = [comp_value, cutoff_datetime]
            kickoff = before_kickoff or target["scheduled_at"]
            if kickoff:
                sql += " AND julianday(o.match_date) < julianday(?)"
                params.append(kickoff)
            sql += " ORDER BY o.match_date ASC LIMIT ?"
            params.append(limit)
            return [dict(r) for r in conn.execute(sql, params).fetchall()]
        finally:
            conn.close()

    def get_team_recent_matches(self, team_id: int, cutoff_datetime: str, limit: int = 5,
                                before_kickoff: Optional[str] = None) -> List[Dict[str, Any]]:
        conn = self._get_connection()
        try:
            # Striktní filtrace zápasů se scheduled_at <= cutoff_datetime (Data Leakage Prevention);
            # volitelně navíc jen zápasy před výkopem cílového zápasu (backtest / zpětná analýza).
            kickoff_sql = " AND julianday(m.scheduled_at) < julianday(?)" if before_kickoff else ""
            params: List[Any] = [team_id, team_id, cutoff_datetime] + ([before_kickoff] if before_kickoff else []) + [limit]
            rows = conn.execute("""
                SELECT m.id as match_id, m.home_team_id, m.away_team_id, m.scheduled_at,
                       ms.home_goals, ms.away_goals, ms.home_shots, ms.away_shots,
                       ms.home_xg, ms.away_xg, ms.home_xga, ms.away_xga,
                       ms.home_npxg, ms.away_npxg, ms.home_gs_adj_xg, ms.away_gs_adj_xg
                FROM matches m
                JOIN match_statistics ms ON m.id = ms.match_id
                WHERE (m.home_team_id = ? OR m.away_team_id = ?)
                  AND julianday(m.scheduled_at) <= julianday(?)
                  AND ms.home_goals IS NOT NULL AND ms.away_goals IS NOT NULL""" + kickoff_sql + """
                ORDER BY m.scheduled_at DESC
                LIMIT ?
            """, params).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_head_to_head(self, home_team_id: int, away_team_id: int,
                         cutoff_datetime: str, limit: int = 8,
                         before_kickoff: Optional[str] = None) -> List[Dict[str, Any]]:
        """Return only completed H2H matches available before the research cutoff."""
        conn = self._get_connection()
        try:
            kickoff_sql = " AND julianday(m.scheduled_at) < julianday(?)" if before_kickoff else ""
            params: List[Any] = [home_team_id, away_team_id, away_team_id, home_team_id, cutoff_datetime] \
                + ([before_kickoff] if before_kickoff else []) + [limit]
            rows = conn.execute("""
                SELECT m.id as match_id, m.home_team_id, m.away_team_id, m.scheduled_at,
                       ms.home_goals, ms.away_goals, ms.home_xg, ms.away_xg,
                       ms.home_xga, ms.away_xga
                FROM matches m
                JOIN match_statistics ms ON m.id = ms.match_id
                WHERE ((m.home_team_id = ? AND m.away_team_id = ?)
                    OR (m.home_team_id = ? AND m.away_team_id = ?))
                  AND julianday(m.scheduled_at) <= julianday(?)
                  AND ms.home_goals IS NOT NULL AND ms.away_goals IS NOT NULL""" + kickoff_sql + """
                ORDER BY m.scheduled_at DESC
                LIMIT ?
            """, params).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_team_xg_rates(self, team_id: int, venue: str, cutoff_datetime: str,
                          before_kickoff: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Get pre-match xG for/against rates; prefer dated observations, then season snapshot."""
        conn = self._get_connection()
        try:
            sql = """SELECT match_date, home_team_id, away_team_id, home_xg, away_xg,
                            home_npxg, away_npxg, home_gs_adj_xg, away_gs_adj_xg
                     FROM match_xg_observations
                     WHERE (home_team_id=? OR away_team_id=?)
                       AND julianday(match_date) <= julianday(?)"""
            params: List[Any] = [team_id, team_id, cutoff_datetime]
            if before_kickoff:
                sql += " AND julianday(match_date) < julianday(?)"
                params.append(before_kickoff)
            sql += " ORDER BY match_date DESC"
            observations = [dict(r) for r in conn.execute(sql, params).fetchall()]
            if len(observations) >= 3:
                vals = {"all": [], "home": [], "away": []}
                for row in observations:
                    is_home = int(row["home_team_id"]) == int(team_id)
                    pair = (float(row["home_xg"] if is_home else row["away_xg"]),
                            float(row["away_xg"] if is_home else row["home_xg"]))
                    vals["all"].append(pair)
                    vals["home" if is_home else "away"].append(pair)
                sample = vals[venue] if len(vals[venue]) >= 3 else vals["all"]
                attack = sum(v[0] for v in sample) / len(sample)
                defence = sum(v[1] for v in sample) / len(sample)
                return {"attack": attack, "defence": defence, "sample_size": len(sample),
                        "venue_split_used": len(vals[venue]) >= 3,
                        "source": "match_xg_observations"}

            row = conn.execute("""SELECT metrics_json, data_cutoff_at FROM team_season_snapshots
                WHERE team_id=? AND competition='Chance Liga'
                  AND julianday(data_cutoff_at) <= julianday(?)
                ORDER BY data_cutoff_at DESC, season DESC LIMIT 1""", (team_id, cutoff_datetime)).fetchone()
            if not row:
                if not observations:
                    return None
                vals = []
                for item in observations:
                    is_home = int(item["home_team_id"]) == int(team_id)
                    vals.append((float(item["home_xg"] if is_home else item["away_xg"]),
                                 float(item["away_xg"] if is_home else item["home_xg"])))
                return {"attack": sum(v[0] for v in vals) / len(vals),
                        "defence": sum(v[1] for v in vals) / len(vals),
                        "sample_size": len(vals), "venue_split_used": False,
                        "source": "match_xg_observations"}
            metrics = json.loads(row["metrics_json"])
            prefix = "home" if venue == "home" else "away"
            attack = metrics.get(f"xg_for_{prefix}")
            defence = metrics.get(f"xg_against_{prefix}")
            if attack is None or defence is None:
                attack, defence = metrics.get("xg_for"), metrics.get("xg_against")
            if attack is None or defence is None:
                return None
            return {"attack": float(attack), "defence": float(defence),
                    "sample_size": int(metrics.get(f"{prefix}_matches") or metrics.get("matches") or 0),
                    "venue_split_used": metrics.get(f"{prefix}_matches", 0) >= 3,
                    "source": "team_season_snapshots", "data_cutoff_at": row["data_cutoff_at"]}
        finally:
            conn.close()

    def save_snapshot(self, run_id: Any, match_id: Optional[int], team_id: Optional[int],
                      metric: str, value: Optional[float], sample_size: int,
                      coverage: float, data_cutoff_at: str, calculation_version: str = "1.0.0") -> int:
        conn = self._get_connection()
        try:
            # statistical_snapshots.run_id references runs.id (INTEGER).
            # Handle both integer runs.id and string run_id
            if isinstance(run_id, int):
                run_row = conn.execute("SELECT id FROM runs WHERE id = ?", (run_id,)).fetchone()
            else:
                run_row = conn.execute("SELECT id FROM runs WHERE run_id = ?", (str(run_id),)).fetchone()
                if not run_row and str(run_id).isdigit():
                    run_row = conn.execute("SELECT id FROM runs WHERE id = ?", (int(run_id),)).fetchone()

            if not run_row:
                raise ValueError(f"Run {run_id} does not exist in runs table")
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO statistical_snapshots (
                    run_id, match_id, team_id, metric, value, sample_size, coverage, data_cutoff_at, calculation_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id, COALESCE(team_id, -1), metric, data_cutoff_at, calculation_version) DO UPDATE SET
                    match_id=excluded.match_id,
                    value=excluded.value,
                    sample_size=excluded.sample_size,
                    coverage=excluded.coverage,
                    created_at=CURRENT_TIMESTAMP
            """, (int(run_row["id"]), match_id, team_id, metric, value, sample_size, coverage, data_cutoff_at, calculation_version))
            conn.commit()
            return cursor.lastrowid
        finally:
            conn.close()
