from app.statistics.aggregates import AggregateEngine

def test_aggregate_coverage():
    # 3 z 5 dat jsou platná = coverage 60%
    xg_values = [1.5, 2.1, None, 0.8, None]
    res = AggregateEngine.calculate_metric_aggregate(xg_values)
    
    assert res["total_samples"] == 5
    assert res["valid_samples"] == 3
    assert res["coverage"] == 0.6
    assert res["average"] == 1.4666666666666668