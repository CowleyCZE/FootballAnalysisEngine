"""TODO 11.22: načítání config/model_params.yaml a izolace testů od laděných parametrů."""
import os

from app.statistics.score_predictor import ExactScorePredictor, load_tuned_params


def test_tests_start_with_default_params():
    for key, value in ExactScorePredictor._DEFAULT_PARAMS.items():
        assert getattr(ExactScorePredictor, key) == value
    assert ExactScorePredictor._TUNED == {}


def test_load_tuned_params_from_file(tmp_path):
    cfg = tmp_path / "model_params.yaml"
    cfg.write_text("params:\n  DC_RHO: -0.12\n  FORM_DECAY: 0.2\n  UNKNOWN: 1\n  PRIOR_WEIGHT: 99\n", encoding="utf-8")
    applied = load_tuned_params(str(cfg))
    assert applied == {"DC_RHO": -0.12, "FORM_DECAY": 0.2}  # neznámý klíč a hodnota mimo rozsah se ignorují
    assert ExactScorePredictor.DC_RHO == -0.12
    assert ExactScorePredictor.PRIOR_WEIGHT == ExactScorePredictor._DEFAULT_PARAMS["PRIOR_WEIGHT"]


def test_load_tuned_params_missing_file_changes_nothing(tmp_path):
    assert load_tuned_params(str(tmp_path / "neexistuje.yaml")) == {}
    assert ExactScorePredictor._TUNED == {}


def test_load_tuned_params_disabled_by_env(tmp_path, monkeypatch):
    cfg = tmp_path / "model_params.yaml"
    cfg.write_text("params:\n  DC_RHO: -0.12\n", encoding="utf-8")
    monkeypatch.setenv("FAE_TUNED_PARAMS", "0")
    assert load_tuned_params(str(cfg)) == {}
    assert ExactScorePredictor.DC_RHO == ExactScorePredictor._DEFAULT_PARAMS["DC_RHO"]
