from datetime import datetime, timezone
from typing import Optional, Tuple, Union


class CutoffFilter:
    @staticmethod
    def _to_utc_naive(dt: Union[datetime, str, None]) -> Optional[datetime]:
        if dt is None:
            return None
        if isinstance(dt, str):
            try:
                dt = datetime.fromisoformat(dt.replace("Z", "+00:00"))
            except ValueError:
                return None
        if dt.tzinfo is not None:
            return dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt

    @classmethod
    def validate(
        cls,
        published_at: Optional[Union[datetime, str]],
        cutoff_at: Union[datetime, str],
        policy: str = "allow_unknown"
    ) -> Tuple[bool, str]:
        pub_dt = cls._to_utc_naive(published_at)
        cutoff_dt = cls._to_utc_naive(cutoff_at)

        if cutoff_dt is None:
            return True, "VALID"

        if pub_dt is None:
            if policy == "exclude":
                return False, "DATE_UNKNOWN"
            return True, "DATE_UNKNOWN_ALLOWED"

        if pub_dt > cutoff_dt:
            return False, "EXCLUDED_BY_CUTOFF"

        return True, "VALID"
