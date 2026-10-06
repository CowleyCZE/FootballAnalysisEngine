from typing import List
from datetime import datetime
from app.research.models import Claim, ClaimStatus
from app.research.cutoff_filter import CutoffFilter


class ClaimValidator:
    def validate_claims(self, claims: List[Claim], cutoff_at: datetime) -> List[Claim]:
        validated = []
        for claim in claims:
            if not claim.evidence_list:
                claim.status = ClaimStatus.REJECTED
                validated.append(claim)
                continue

            # Check claim's own source_date against cutoff
            if claim.source_date:
                passed, _ = CutoffFilter.validate(claim.source_date, cutoff_at, policy="allow_unknown")
                if not passed:
                    claim.status = ClaimStatus.REJECTED
                    validated.append(claim)
                    continue

            # Check all attached evidence published_at against cutoff
            valid_ev = True
            for ev in claim.evidence_list:
                passed, _ = CutoffFilter.validate(ev.published_at, cutoff_at, policy="allow_unknown")
                if not passed:
                    valid_ev = False
                    break

            if not valid_ev:
                claim.status = ClaimStatus.REJECTED
            else:
                claim.status = ClaimStatus.VALID

            validated.append(claim)
        return validated
