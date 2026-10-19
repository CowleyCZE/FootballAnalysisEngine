from app.statistics.models import MatchStatistics
from app.statistics.validators import StatisticsValidator

def test_statistics_validator():
    validator = StatisticsValidator()
    
    # Validní statistika
    valid_stats = MatchStatistics(
        match_id=1, home_goals=2, away_goals=1,
        home_shots=10, home_shots_on_target=4,
        home_possession=55.0, away_possession=45.0
    )
    is_valid, errors = validator.validate(valid_stats)
    assert is_valid is True
    assert len(errors) == 0

    # Neplatná statistika (SOT > Shots)
    invalid_stats = MatchStatistics(
        match_id=2, home_shots=5, home_shots_on_target=8
    )
    is_valid, errors = validator.validate(invalid_stats)
    assert is_valid is False
    assert "Domácí SOT" in errors[0]