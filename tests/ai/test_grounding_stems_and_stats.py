"""Běh M976_1fad: přísnější vazba faktoru na důkaz a statistické věty v závěru AI větve."""
from app.workers.ai_worker import AIWorker

TEAMS = ["Zlín", "Slovácko"]


def test_single_shared_stem_is_not_enough():
    factor = "Zápas mezi Zlíny a Slováckem se odehrála v návratovém zápasu v září."
    evidence = "Zlín porazil Slovácko 1:0 v derby, které se odehrálo v sobotu."
    assert AIWorker._factor_is_grounded(factor, [evidence], TEAMS) is False


def test_two_shared_stems_pass():
    factor = "Zlín porazil Slovácko v derby gólem v desáté minutě."
    evidence = "Zlín porazil Slovácko 1:0, o derby rozhodl gól v desáté minutě."
    assert AIWorker._factor_is_grounded(factor, [evidence], TEAMS) is True


def test_min_stems_env(monkeypatch):
    monkeypatch.setenv("FAE_AI_GROUNDING_MIN_STEMS", "1")
    factor = "Zápas mezi Zlíny a Slováckem se odehrála v návratovém zápasu v září."
    assert AIWorker._factor_is_grounded(factor, ["Derby se odehrálo v sobotu."], TEAMS) is True


def test_ai_conclusion_gets_statistical_sentences():
    context = {
        "match": {"home_team": "Zlín", "away_team": "Slovácko"},
        "statistics": {
            "prediction": {"predicted_score": "1-1", "prior_only": False},
            "snapshots": [
                {"team": "home", "metric": "form_points", "value": 3.0, "sample_size": 5, "coverage": 0.65},
                {"team": "away", "metric": "form_points", "value": 3.0, "sample_size": 5, "coverage": 0.65},
            ],
        },
    }
    text = AIWorker._with_tip_sentence("Vlastní závěr AI.", context)
    assert text.startswith("Statistický model tipuje výsledek 1:1")
    assert "Forma (body z posledních odehraných zápasů): Zlín 3 b. z 5 zápasů, Slovácko 3 b. z 5 zápasů." in text
    assert text.endswith("Vlastní závěr AI.")


def test_conclusion_unchanged_without_snapshots():
    context = {"match": {}, "statistics": {"prediction": {"predicted_score": "2-0"}}}
    text = AIWorker._with_tip_sentence("Závěr.", context)
    assert text == "Statistický model tipuje výsledek 2:0. Závěr."
