from __future__ import annotations

from app.statistics.calibration import PlattCalibrator, brier_score_1x2, calibration_curve


def test_platt_calibrator_improves_overconfident_predictions():
    # Overconfident raw predictions on synthetic historical data.
    preds = []
    outcomes = []
    for i in range(60):
        if i % 3 == 0:
            preds.append((0.90, 0.05, 0.05))
            outcomes.append(0 if i % 6 == 0 else 1)
        elif i % 3 == 1:
            preds.append((0.05, 0.90, 0.05))
            outcomes.append(1 if i % 6 == 1 else 2)
        else:
            preds.append((0.05, 0.05, 0.90))
            outcomes.append(2 if i % 6 == 2 else 0)

    raw_brier = brier_score_1x2(preds, outcomes)
    calibrator = PlattCalibrator.fit(preds, outcomes)
    cal_preds = [calibrator.calibrate(*p) for p in preds]
    cal_brier = brier_score_1x2(cal_preds, outcomes)

    assert raw_brier is not None and cal_brier is not None
    assert cal_brier < raw_brier
    for p in cal_preds:
        assert abs(sum(p) - 1.0) < 1e-6
        assert all(0.0 < x < 1.0 for x in p)


def test_calibrator_save_and_load_roundtrip(tmp_path):
    target = str(tmp_path / "calibration_params.json")
    cal = PlattCalibrator({"home": (0.85, 0.05), "draw": (0.9, -0.02), "away": (0.8, 0.01)})
    cal.save(target)
    loaded = PlattCalibrator.load(target)
    assert loaded is not None
    assert loaded.params == cal.params


def test_calibration_curve_returns_ece_and_bins():
    preds = [(0.6, 0.2, 0.2), (0.2, 0.6, 0.2), (0.2, 0.2, 0.6)]
    outcomes = [0, 1, 2]
    report = calibration_curve(preds, outcomes, bins=5)
    assert report["ece"] is not None
    assert len(report["bins"]) > 0
