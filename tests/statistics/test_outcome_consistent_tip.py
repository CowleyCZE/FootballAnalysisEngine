"""TODO 11.32: tip přesného skóre musí ležet uvnitř nejpravděpodobnějšího výsledku 1-X-2 (ne jen modus mřížky)."""
import pytest

from app.statistics.score_predictor import ExactScorePredictor


def _row(mid, home, away, hg, ag, day):
    return {"match_id": mid, "home_team_id": home, "away_team_id": away, "home_goals": hg, "away_goals": ag,
            "scheduled_at": f"2026-09-{day:02d}T15:00:00+00:00"}


def _outcome(h, a):
    return "home" if h > a else "draw" if h == a else "away"


def _favoured(pred):
    probs = {"home": pred["home_win_probability"], "draw": pred["draw_probability"], "away": pred["away_win_probability"]}
    return max(probs, key=probs.get)


SCENARIOS = {
    "prior_only": [],
    "away_dominant": [_row(i, 3, 2, 0, 3, i) for i in range(1, 5)] + [_row(10 + i, 1, 3, 0, 2, i) for i in range(1, 5)],
    "home_dominant": [_row(i, 1, 3, 3, 0, i) for i in range(1, 5)] + [_row(10 + i, 3, 2, 0, 2, i) for i in range(1, 5)],
    "balanced": [_row(i, 1, 3, 1, 1, i) for i in range(1, 5)] + [_row(10 + i, 3, 2, 1, 1, i) for i in range(1, 5)],
}


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_tip_is_consistent_with_most_probable_outcome(name):
    pred = ExactScorePredictor.predict(SCENARIOS[name], 1, 2)
    tip = _outcome(pred["predicted_home_goals"], pred["predicted_away_goals"])
    assert tip == _favoured(pred) == pred["factors"]["tip_outcome"]
    # modus mřížky se vždy uvádí pro transparentnost
    assert pred["factors"]["modal_score"] in {f"{h}-{a}" for h in range(8) for a in range(8)}


def test_modal_draw_is_replaced_when_a_team_is_favoured():
    """Typický případ M979: modus 1:1, ale favorizovaný je jeden z týmů → tip nesmí být remíza."""
    for name, rows in SCENARIOS.items():
        pred = ExactScorePredictor.predict(rows, 1, 2)
        if pred["factors"]["modal_score"] in {"0-0", "1-1", "2-2"} and _favoured(pred) != "draw":
            assert pred["predicted_home_goals"] != pred["predicted_away_goals"], name
            assert pred["factors"]["tip_is_modal_score"] is False


def test_tip_is_most_probable_score_within_favoured_outcome():
    pred = ExactScorePredictor.predict(SCENARIOS["away_dominant"], 1, 2)
    scores = pred["score_probabilities"]  # top 10 sestupně
    favoured = _favoured(pred)
    in_outcome = [k for k in scores if _outcome(*map(int, k.split("-"))) == favoured]
    assert f"{pred['predicted_home_goals']}-{pred['predicted_away_goals']}" == in_outcome[0]


def test_flag_off_restores_modal_score(monkeypatch):
    monkeypatch.setattr(ExactScorePredictor, "OUTCOME_CONSISTENT_TIP", False)
    for rows in SCENARIOS.values():
        pred = ExactScorePredictor.predict(rows, 1, 2)
        top = next(iter(pred["score_probabilities"]))
        assert f"{pred['predicted_home_goals']}-{pred['predicted_away_goals']}" == top
        assert pred["factors"]["tip_is_modal_score"] is True
