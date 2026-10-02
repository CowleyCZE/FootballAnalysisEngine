import sqlite3
from typing import List, Dict, Any, Optional
from app.statistics.models import MatchStatistics

class StatisticsRepository:
    def __init__(self, db_path: str = "database/football.db"):
        self.db_path = db_path

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
                    home_npxg, away_npxg, xg_metric_definition
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(match_id) DO UPDATE SET
                    home_goals=excluded.home_goals, away_goals=excluded.away_goals,
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
                stats.home_npxg, stats.away_npxg, stats.xg_metric_definition
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

    def get_team_recent_matches(self, team_id: int, cutoff_datetime: str, limit: int = 5) -> List[Dict[str, Any]]:
        conn = self._get_connection()
        try:
            # Striktní filtrace zápasů se scheduled_at <= cutoff_datetime (Data Leakage Prevention)
            rows = conn.execute("""
                SELECT m.id as match_id, m.home_team_id, m.away_team_id, m.scheduled_at,
                       ms.home_goals, ms.away_goals, ms.home_shots, ms.away_shots, ms.home_xg, ms.away_xg
                FROM matches m
                JOIN match_statistics ms ON m.id = ms.match_id
                WHERE (m.home_team_id = ? OR m.away_team_id = ?)
                  AND m.scheduled_at <= ?
                ORDER BY m.scheduled_at DESC
                LIMIT ?
            """, (team_id, team_id, cutoff_datetime, limit)).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def save_snapshot(self, run_id: int, match_id: Optional[int], team_id: Optional[int],
                      metric: str, value: Optional[float], sample_size: int,
                      coverage: float, data_cutoff_at: str, calculation_version: str = "1.0.0") -> int:
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO statistical_snapshots (
                    run_id, match_id, team_id, metric, value, sample_size, coverage, data_cutoff_at, calculation_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (run_id, match_id, team_id, metric, value, sample_size, coverage, data_cutoff_at, calculation_version))
            conn.commit()
            return cursor.lastrowid
        finally:
            conn.close()