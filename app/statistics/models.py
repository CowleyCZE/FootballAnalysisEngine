from dataclasses import dataclass
from typing import Optional

@dataclass
class MatchStatistics:
    match_id: int
    
    # Góly - Celý zápas (FT)
    home_goals: Optional[int] = None
    away_goals: Optional[int] = None
    
    # Góly - Poločas (HT)
    home_ht_goals: Optional[int] = None
    away_ht_goals: Optional[int] = None
    home_ft_goals: Optional[int] = None
    away_ft_goals: Optional[int] = None
    
    # Střely
    home_shots: Optional[int] = None
    away_shots: Optional[int] = None
    home_shots_on_target: Optional[int] = None
    away_shots_on_target: Optional[int] = None
    
    # Držení míče (0-100)
    home_possession: Optional[float] = None
    away_possession: Optional[float] = None
    
    # Rohy
    home_corners: Optional[int] = None
    away_corners: Optional[int] = None
    
    # Karty
    home_yellow_cards: Optional[int] = None
    away_yellow_cards: Optional[int] = None
    home_red_cards: Optional[int] = None
    away_red_cards: Optional[int] = None
    
    # Očekávané góly (xG)
    home_xg: Optional[float] = None
    away_xg: Optional[float] = None
    home_xga: Optional[float] = None
    away_xga: Optional[float] = None
    home_npxg: Optional[float] = None
    away_npxg: Optional[float] = None
    
    # Metadata zdrojů
    xg_metric_definition: Optional[str] = None