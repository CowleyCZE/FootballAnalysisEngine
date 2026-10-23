import sqlite3

import menu
from app.database.match_cleanup import delete_matches_cascade
from app.database.schema import initialize_database
from app.statistics import history_autofill
from app.statistics.history_autofill import HistoryAutoFiller


def _db(tmp_path):
    db = str(tmp_path / "t.db")
    initialize_database(db)
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO teams(id, name, normalized_name) VALUES (1, 'Teplice', 'teplice'), (2, 'Artis Brno', 'artis brno'), (3, 'Sparta Praha', 'sparta praha')")
        conn.execute("INSERT INTO competitions(id, name) VALUES (1, 'Chance Liga')")
        # cílový (zadaný) zápas
        conn.execute("INSERT INTO matches(id, competition, competition_id, home_team_id, away_team_id, scheduled_at, status) VALUES (1, 'Chance Liga', 1, 1, 2, '2026-10-24T13:00:00+00:00', 'RESOLVED')")
        # historický zápas s výsledkem
        conn.execute("INSERT INTO matches(id, competition, competition_id, home_team_id, away_team_id, scheduled_at, status) VALUES (2, 'Chance Liga', 1, 3, 1, '2026-09-01T15:00:00+00:00', 'RESOLVED')")
        conn.execute("INSERT INTO match_statistics(match_id, home_goals, away_goals) VALUES (2, 1, 0)")
    return db


def test_delete_cascade_removes_entered_match_but_keeps_history(tmp_path):
    db = _db(tmp_path)
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO runs(id, run_id, status, started_at) VALUES (1, 'RUN-1', 'RUNNING', '2026-10-22T10:00:00Z')")
        conn.execute("INSERT INTO pipeline_runs(run_id, match_id, state, started_at, updated_at) VALUES ('RUN-1', 1, 'UNRESOLVED', '2026-10-22T10:00:00Z', '2026-10-22T10:01:00Z')")
        conn.execute("INSERT INTO jobs(id, job_id, run_id, match_id, job_type, status) VALUES (1, 'J1', 'RUN-1', 1, 'STATISTICS', 'SUCCESS'), (2, 'J2', 'RUN-1', 1, 'AI_ANALYSIS', 'PENDING')")
        conn.execute("INSERT INTO job_dependencies(job_id, depends_on_job_id) VALUES (2, 1)")
        conn.execute("INSERT INTO claims(run_id, match_id, claim_text, status) VALUES (1, 1, 'x', 'VALID')")
        conn.execute("INSERT INTO statistical_snapshots(run_id, match_id, team_id, metric, value, sample_size, coverage, data_cutoff_at, calculation_version) VALUES (1, 1, 1, 'form_points', 0, 0, 0, '2026-10-22T10:00:00', '1.0.0')")
        deleted = delete_matches_cascade(conn, [1, 2])  # 2 má výsledek -> chráněn
    assert deleted == 1
    with sqlite3.connect(db) as conn:
        assert [r[0] for r in conn.execute("SELECT id FROM matches")] == [2]
        for table in ("pipeline_runs", "jobs", "job_dependencies", "claims", "statistical_snapshots", "runs"):
            assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0, table
        assert conn.execute("SELECT COUNT(*) FROM teams").fetchone()[0] == 3


def test_menu_lists_only_entered_matches_and_deletes(tmp_path, monkeypatch):
    db = _db(tmp_path)
    monkeypatch.setattr(menu, "DB_PATH", db)
    assert [r["id"] for r in menu.list_entered_matches()] == [1]
    answers = iter(("1", "ano"))
    monkeypatch.setattr("builtins.input", lambda _p="": next(answers))
    menu.delete_entered_matches()
    with sqlite3.connect(db) as conn:
        assert [r[0] for r in conn.execute("SELECT id FROM matches")] == [2]


def _fake_get_json(url, timeout=20.0):
    if "api.github.com" in url:
        return {"tree": []}
    if "searchteams.php" in url:
        query = url.split("t=", 1)[1]
        if query.startswith("Teplice"):
            return {"teams": [{"idTeam": "10", "strTeam": "FK Teplice", "strSport": "Soccer"}]}
        if "Zbrojovka" in query and "FC" not in query:
            return {"teams": [{"idTeam": "11", "strTeam": "FC Zbrojovka Brno", "strSport": "Soccer"}]}
        return {"teams": None}
    if "eventslast.php?id=10" in url:
        return {"results": [
            {"idEvent": str(100 + i), "dateEvent": f"2026-10-{i:02d}", "strTime": "15:00:00", "strHomeTeam": "FK Teplice",
             "strAwayTeam": "Opponent", "intHomeScore": "2", "intAwayScore": "1", "strLeague": "Czech First League", "strSeason": "2026-2027"}
            for i in range(1, 6)
        ] + [
            {"idEvent": "200", "dateEvent": "2026-10-20", "strHomeTeam": "FK Teplice", "strAwayTeam": "Nedohrano", "intHomeScore": None, "intAwayScore": None},
            {"idEvent": "201", "dateEvent": "2026-10-30", "strHomeTeam": "FK Teplice", "strAwayTeam": "Budoucnost", "intHomeScore": "1", "intAwayScore": "1"},
        ]}
    if "eventslast.php?id=11" in url:
        return {"results": [
            {"idEvent": str(300 + i), "dateEvent": f"2026-10-{i:02d}", "strTime": "15:00:00", "strHomeTeam": "Soupeř",
             "strAwayTeam": "FC Zbrojovka Brno", "intHomeScore": "0", "intAwayScore": "0", "strLeague": "Czech First League", "strSeason": "2026-2027"}
            for i in range(1, 6)
        ]}
    return {}


def test_online_results_fill_history_for_target_teams(tmp_path, monkeypatch):
    db = _db(tmp_path)
    with sqlite3.connect(db) as conn:
        conn.execute("DELETE FROM match_statistics")
        conn.execute("DELETE FROM matches WHERE id=2")
    monkeypatch.setenv("FAE_AUTO_HISTORY", "1")
    monkeypatch.setenv("FAE_ONLINE_HISTORY", "1")
    monkeypatch.setattr(history_autofill, "_get_json", _fake_get_json)
    result = HistoryAutoFiller(db_path=db, cache_dir=tmp_path / "c").ensure(1, 2, "Chance Liga", "2026-10-22T03:38:48")
    assert result["status"] == "imported"
    assert result["imported"] == 10  # bez nedohraného a budoucího zápasu
    assert not any("zastaral" in w for w in result["warnings"])
    with sqlite3.connect(db) as conn:
        home = conn.execute("SELECT COUNT(*) FROM matches WHERE home_team_id=1 OR away_team_id=1").fetchone()[0]
        away = conn.execute("SELECT COUNT(*) FROM matches WHERE (home_team_id=2 OR away_team_id=2) AND id != 1").fetchone()[0]
    assert home == 5 + 1 and away == 5  # +1 = cílový zápas

    # Druhé volání nic nezdvojí
    again = HistoryAutoFiller(db_path=db, cache_dir=tmp_path / "c").ensure(1, 2, "Chance Liga", "2026-10-22T03:38:48")
    assert again["imported"] == 0
