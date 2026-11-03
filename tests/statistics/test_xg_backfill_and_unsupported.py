"""TODO 11.34 – nepodporované metriky feedu a doplnění xG z pozorování."""
import sqlite3

from app.statistics.csv_data_sync import backfill_xg_from_observations, import_csv_files
from app.statistics.team_features import metric_availability

RESULTS = (
    "date,home_team,away_team,home_goals,away_goals,competition\n"
    "2026-09-12,Sparta Praha,Slavia Praha,2,1,Chance Liga\n"
    "2026-09-20,Slavia Praha,Sparta Praha,0,0,Chance Liga\n"
)
XG = (
    "date,home_team,away_team,home_xg,away_xg,competition\n"
    "2026-09-12,Sparta Praha,Slavia Praha,1.7,0.8,Chance Liga\n"
    "2026-09-21,Slavia Praha,Sparta Praha,1.1,0.9,Chance Liga\n"  # +1 den (časové pásmo)
)


def test_metric_availability_marks_only_empty_feed_dependent_metrics():
    assert metric_availability("npxg_for_ewma", None, 0) == "UNSUPPORTED_BY_FEED"
    assert metric_availability("game_state_adj_xg_for_ewma", None, None) == "UNSUPPORTED_BY_FEED"
    assert metric_availability("npxg_for_ewma", 1.2, 3) is None      # má data
    assert metric_availability("xgd_ewma", None, 0) is None           # není závislá na feedu
    assert metric_availability("form_points", None, 0) is None


def test_missing_match_xg_is_backfilled_from_observations(tmp_path):
    db = tmp_path / "bf.db"
    results = tmp_path / "chance_liga_dataset.csv"
    results.write_text(RESULTS, encoding="utf-8")
    xg = tmp_path / "czech_league_xg_dataset.csv"
    xg.write_text(XG, encoding="utf-8")
    # nejdřív jen výsledky, pak sparse xG soubor (pozorování) → doplnění při importu
    import_csv_files([results], db)
    out = import_csv_files([xg], db)
    assert out["xg_rows"] == 2 and out["xg_backfilled"] == 2
    with sqlite3.connect(db) as conn:
        rows = conn.execute("SELECT home_xg, away_xg FROM match_statistics ORDER BY match_id").fetchall()
    assert sorted(rows) == [(1.1, 0.9), (1.7, 0.8)]


def test_backfill_never_overwrites_existing_xg(tmp_path):
    db = tmp_path / "bf2.db"
    results = tmp_path / "chance_liga_dataset.csv"
    results.write_text(RESULTS, encoding="utf-8")
    import_csv_files([results], db)
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE match_statistics SET home_xg=3.0, away_xg=3.0")
        conn.commit()
    xg = tmp_path / "czech_league_xg_dataset.csv"
    xg.write_text(XG, encoding="utf-8")
    import_csv_files([xg], db)
    with sqlite3.connect(db) as conn:
        assert backfill_xg_from_observations(conn) == 0
        assert conn.execute("SELECT COUNT(*) FROM match_statistics WHERE home_xg=3.0").fetchone()[0] == 2
