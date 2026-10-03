from datetime import datetime
from typing import Optional, Tuple

class CutoffFilter:
    @staticmethod
    def validate(published_at: Optional[datetime], cutoff_at: datetime, policy: str = "exclude") -> Tuple[bool, str]:
        if published_at is None:
            if policy == "exclude":
                return False, "DATE_UNKNOWN"
            return True, "DATE_UNKNOWN_ALLOWED"

        pub_naive = published_at.replace(tzinfo=None)
        cutoff_naive = cutoff_at.replace(tzinfo=None)

        if pub_naive > cutoff_naive:
            return False, "EXCLUDED_BY_CUTOFF"

        return True, "VALID"
