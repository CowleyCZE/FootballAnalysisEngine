import uuid
from typing import List, Dict
from datetime import datetime
from app.research.models import Claim, ClaimStatus

class ConflictDetector:
    def detect_and_resolve(self, claims: List[Claim]) -> List[Claim]:
        grouped: Dict[str, List[Claim]] = {}

        for c in claims:
            if c.status == ClaimStatus.VALID:
                grouped.setdefault(c.subject, []).append(c)

        for subject, subject_claims in grouped.items():
            if len(subject_claims) > 1:
                statuses = set(c.object_value for c in subject_claims)
                if len(statuses) > 1:
                    group_id = f"CONFLICT-{uuid.uuid4().hex[:6]}"
                    
                    subject_claims.sort(key=lambda x: x.source_date or datetime.min)
                    
                    latest_date = subject_claims[-1].source_date
                    earliest_date = subject_claims[0].source_date

                    if latest_date and earliest_date and latest_date > earliest_date:
                        for c in subject_claims[:-1]:
                            c.status = ClaimStatus.SUPERSEDED
                        subject_claims[-1].status = ClaimStatus.VALID
                    else:
                        for c in subject_claims:
                            c.status = ClaimStatus.CONFLICTED
                            c.conflict_group_id = group_id

        return claims
