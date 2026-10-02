from app.statistics.normalizer import SourceNormalizer

def test_source_normalizer():
    norm = SourceNormalizer()
    
    assert norm.parse_int("14") == 14
    assert norm.parse_int("-") is None
    assert norm.parse_float("58.5%") == 58.5
    assert norm.parse_float("58,5") == 58.5
    
    home, away = norm.parse_score(" 2 - 1 ")
    assert home == 2
    assert away == 1