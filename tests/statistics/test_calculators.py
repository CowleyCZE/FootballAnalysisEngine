from app.statistics.calculators import StatisticsCalculator

def test_calculators():
    calc = StatisticsCalculator()
    
    # Test výsledku a bodů
    res, pts = calc.calculate_result(2, 0, is_home=True)
    assert res == "W" and pts == 3

    res, pts = calc.calculate_result(1, 1, is_home=False)
    assert res == "D" and pts == 1

    # Test průměru s ignorováním None
    vals = [12.0, None, 15.0, 7.0, 10.0]
    assert calc.calculate_average(vals) == 11.0

    # Test mediánu
    assert calc.calculate_median([1, 2, 100]) == 2.0