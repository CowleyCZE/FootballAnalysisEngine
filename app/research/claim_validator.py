from typing import List
from app.research.models import Claim, ClaimStatus
from app.research.cutoff_filter import CutoffFilter
from datetime import datetime

class ClaimValidator:
    def validate_claims(self, claims: List[Claim], cutoff_at: datetime) -> List[Claim]:
        validated = []
        for claim in claims:
            if not claim.evidence_list:
                claim.status = ClaimStatus.REJECTED
                validated.append(claim)
                continue

            valid_ev = True
            for ev in claim.evidence_list:
                passed, _ = CutoffFilter.validate(ev.published_at, cutoff_at, policy="exclude")
                if not passed:
                    valid_ev = False
                    break

            if not valid_ev:
                claim.status = ClaimStatus.REJECTED
            else:
                claim.status = ClaimStatus.VALID

            validated.append(claim)
        return validated
