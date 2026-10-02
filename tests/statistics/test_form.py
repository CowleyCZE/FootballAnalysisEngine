from app.statistics.form import FormEngine

def test_form_engine():
    # 5 testovacích zápasů pro tým 1
    matches = [
        {"home_team_id": 1, "away_team_id": 2, "home_goals": 2, "away_goals": 0}, # W (3b)
        {"home_team_id": 3, "away_team_id": 1, "home_goals": 1, "away_goals": 1}, # D (1b)
        {"home_team_id": 1, "away_team_id": 4, "home_goals": 3, "away_goals": 1}, # W (3b)
        {"home_team_id": 5, "away_team_id": 1, "home_goals": 1, "away_goals": 0}, # L (0b)
        {"home_team_id": 1, "away_team_id": 6, "home_goals": 2, "away_goals": 1}, # W (3b)
    ]
    
    res = FormEngine.calculate_form(matches, team_id=1, last_n=5)
    
    assert res["form_string"] == "W-D-W-L-W"
    assert res["points"] == 10
    assert res["gf"] == 8
    assert res["ga"] == 4
    assert res["gd"] == 4
    assert res["gf_avg"] == 1.6