from datetime import datetime, timezone
import logging

logger = logging.getLogger(__name__)

class FreshnessChecker:
    @staticmethod
    def calculate_freshness(published_at: str, data_type: str = "general") -> dict:
        if not published_at:
            return {"age_hours": 9999.0, "freshness_score": 0.1}

        try:
            pub_dt = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
            if pub_dt.tzinfo is None:
                pub_dt = pub_dt.replace(tzinfo=timezone.utc)
            now = datetime.now(timezone.utc)
            age_hours = max(0.0, (now - pub_dt).total_seconds() / 3600.0)
        except Exception as e:
            logger.warning(f"Failed to parse published_at '{published_at}': {e}")
            return {"age_hours": 9999.0, "freshness_score": 0.1}

        # Half-life decay podle typu dat (v hodinách)
        half_lives = {
            "lineup": 12.0,
            "injury": 48.0,
            "coach": 168.0,
            "statistics": 720.0,
            "general": 120.0
        }
        hl = half_lives.get(data_type, 120.0)
        score = round(max(0.0, 1.0 - (age_hours / (hl * 2.0))), 2)

        return {
            "age_hours": round(age_hours, 1),
            "freshness_score": max(0.0, score)
        }
