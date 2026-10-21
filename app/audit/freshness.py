from datetime import datetime, timezone
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Poločas rozpadu (hodiny) podle typu dat.
HALF_LIVES = {
    "lineup": 12.0,
    "injury": 48.0,
    "coach": 168.0,
    "statistics": 720.0,
    "general": 120.0,
}

# Typ dat podle predikátu claimu (TODO 4.1) – čerstvost sestavy je jiná věc než týmový profil.
PREDICATE_DATA_TYPE = {
    "expected_lineup": "lineup",
    "weather_condition": "lineup",
    "availability_status": "injury",
    "absence_report": "injury",
    "fatigue_context": "injury",
    "team_form": "statistics",
    "team_statistics": "statistics",
    "team_profile_fact": "statistics",
    "h2h_record": "statistics",
    "referee_profile": "statistics",
    "motivation_context": "general",
    "rivalry_context": "general",
    "style_matchup": "general",
}


def data_type_for_predicate(predicate: Optional[str]) -> str:
    return PREDICATE_DATA_TYPE.get(str(predicate or ""), "general")


def _to_utc(value: Any) -> Optional[datetime]:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class FreshnessChecker:
    @staticmethod
    def calculate_freshness(published_at, data_type: str = "general", reference_at: Any = None) -> dict:
        """Stáří důkazu se počítá k `reference_at` (data_cutoff_at), ne k aktuálnímu času;
        bez reference se použije now(). Důkaz novější než reference má stáří 0
        (porušení cutoffu řeší zvlášť CutoffFilter)."""
        if not published_at:
            return {"age_hours": 9999.0, "freshness_score": 0.1}

        try:
            pub_dt = _to_utc(published_at)
            ref_dt = _to_utc(reference_at) or datetime.now(timezone.utc)
            age_hours = max(0.0, (ref_dt - pub_dt).total_seconds() / 3600.0)
        except Exception as e:
            logger.warning(f"Failed to parse published_at '{published_at}': {e}")
            return {"age_hours": 9999.0, "freshness_score": 0.1}

        hl = HALF_LIVES.get(data_type, HALF_LIVES["general"])
        score = round(max(0.0, 1.0 - (age_hours / (hl * 2.0))), 2)

        return {
            "age_hours": round(age_hours, 1),
            "freshness_score": max(0.0, score),
        }
