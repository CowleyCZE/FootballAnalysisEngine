from typing import List
from datetime import datetime
from app.research.models import Claim, ClaimStatus
from app.research.cutoff_filter import CutoffFilter

TIME_SENSITIVE_PREDICATES = {
    "availability_status", "absence_report", "match_identity", "team_form",
    "has_absence", "is_injured", "is_suspended", "is_doubtful", "current_form",
    "expected_lineup", "lineup_status", "weather_condition", "recent_results"
}


class ClaimValidator:
    def validate_claims(self, claims: List[Claim], cutoff_at: datetime) -> List[Claim]:
        validated = []
        for claim in claims:
            if not claim.evidence_list:
                claim.status = ClaimStatus.REJECTED
                validated.append(claim)
                continue

            is_time_sensitive = (
                claim.predicate in TIME_SENSITIVE_PREDICATES
                or "absence" in claim.predicate
                or "form" in claim.predicate
                or "lineup" in claim.predicate
                or "status" in claim.predicate
            )

            # Check claim's own source_date against cutoff
            if claim.source_date:
                passed, reason = CutoffFilter.validate(claim.source_date, cutoff_at, policy="strict_exclude" if is_time_sensitive else "unverified_date")
                if not passed or (is_time_sensitive and reason == "UNVERIFIED_DATE"):
                    claim.status = ClaimStatus.REJECTED
                    validated.append(claim)
                    continue

            # Check all attached evidence published_at against cutoff
            valid_ev = True
            for ev in claim.evidence_list:
                passed, reason = CutoffFilter.validate(ev.published_at, cutoff_at, policy="strict_exclude" if is_time_sensitive else "unverified_date")
                if not passed or (is_time_sensitive and reason == "UNVERIFIED_DATE"):
                    valid_ev = False
                    break

            if not valid_ev:
                claim.status = ClaimStatus.REJECTED
            else:
                claim.status = ClaimStatus.VALID

            validated.append(claim)
        return validated
