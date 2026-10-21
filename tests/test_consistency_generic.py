"""TODO 4.2 – ConsistencyChecker bez natvrdo zadaných čísel, nad skutečnou strukturou statistik."""
from app.audit.consistency import ConsistencyChecker


def _stats(home_form="W-W-D-L-W", home_pts=10, away_form="L-L-D-W-L", away_pts=4, n=5, gf=7, ga=4, gd=3):
    return {
        "home_team": {"form": {"form_string": home_form, "points": home_pts, "sample_size": n, "gf": gf, "ga": ga, "gd": gd}},
        "away_team": {"form": {"form_string": away_form, "points": away_pts, "sample_size": n, "gf": 3, "ga": 9, "gd": -6}},
    }


def _check(stats, conclusion=""):
    return ConsistencyChecker.check_statistical_consistency(stats, [], {"conclusion": conclusion, "key_factors": []})


def test_consistent_real_structure_has_no_issues():
    assert _check(_stats()) == []


def test_points_mismatch_is_detected():
    issues = _check(_stats(home_pts=12))
    assert any(i["type"] == "statistical_inconsistency" and "Body" in i["description"] for i in issues)


def test_goal_difference_mismatch_is_detected():
    issues = _check(_stats(gd=5))
    assert any("Gólový rozdíl" in i["description"] for i in issues)


def test_ai_claim_is_checked_against_real_numbers_not_hardcoded_7_of_10():
    # domácí: 3 výhry z 5 → tvrzení „vyhrál 4 z posledních 5“ je v rozporu
    bad = _check(_stats(), "Domácí vyhráli 4 z posledních 5 zápasů.")
    assert any(i["type"] == "statistical_contradiction" for i in bad)
    ok = _check(_stats(), "Domácí vyhráli 3 z posledních 5 zápasů.")
    assert ok == []


def test_claim_with_different_sample_is_not_verifiable_and_ignored():
    assert _check(_stats(), "Tým vyhrál 7 z posledních 10 zápasů.") == []


def test_legacy_flat_keys_still_work():
    flat = {"wins": 5, "draws": 3, "losses": 2, "matches": 10}
    issues = ConsistencyChecker.check_statistical_consistency(flat, [], {"conclusion": "Tým vyhrál 7 z posledních 10."})
    assert [i["type"] for i in issues] == ["statistical_contradiction"]
    bad_sum = {"wins": 5, "draws": 3, "losses": 3, "matches": 10}
    assert _check(bad_sum)[0]["type"] == "statistical_inconsistency"
