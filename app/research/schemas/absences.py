from dataclasses import dataclass
from typing import Optional
from app.research.models import AbsenceStatus

@dataclass
class AbsenceFact:
    player_name: str
    team_name: str
    status: AbsenceStatus
    reason: Optional[str] = None
    source_date: Optional[str] = None
