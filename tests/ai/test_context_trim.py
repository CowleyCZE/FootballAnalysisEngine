import pytest
from app.ai.context_builder import ContextBuilder

def test_team_profile_trimmed(monkeypatch, tmp_path):
    builder = ContextBuilder(db_path="database/football.db")
    # match 593 has large profiles in team_profile_snapshots
    profiles = builder.load_team_profiles({"match_id": 593}, max_chars=1000)
    for side in ("home", "away"):
        if side in profiles:
            assert len(str(profiles[side]["profile"])) <= 1000

def test_match_context_trimmed(monkeypatch):
    builder = ContextBuilder(db_path="database/football.db")
    ctx = builder.load_match_context({"match_id": 593, "run_id": "20261023_233023_M593_87f6"}, max_chars=500)
    assert len(str(ctx)) <= 500
