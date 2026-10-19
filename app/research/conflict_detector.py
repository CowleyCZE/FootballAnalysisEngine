import uuid
from typing import List, Dict, Tuple
from datetime import datetime, timezone
from app.research.models import Claim, ClaimStatus
from app.research.cutoff_filter import CutoffFilter


class ConflictDetector:
    def detect_and_resolve(self, claims: List[Claim]) -> List[Claim]:
        grouped: Dict[Tuple[str, str], List[Claim]] = {}

        for c in claims:
            if c.status in (ClaimStatus.VALID, ClaimStatus.CANDIDATE):
                key = (c.subject.lower().strip(), c.predicate.lower().strip())
                grouped.setdefault(key, []).append(c)

        for (subj, pred), group in grouped.items():
            if len(group) <= 1:
                continue

            values = set(str(c.object_value).lower().strip() for c in group)
            if len(values) <= 1:
                continue

            # Real conflict on same (subject, predicate) with contradictory values
            group_id = f"CONFLICT-{uuid.uuid4().hex[:6]}"

            def _claim_sort_key(c: Claim):
                dt = c.source_date
                if dt is None and c.evidence_list:
                    dt = c.evidence_list[0].published_at
                normalized_dt = CutoffFilter._to_utc_naive(dt)
                dt_val = normalized_dt.timestamp() if normalized_dt else 0.0
                return (dt_val, c.confidence)

            group.sort(key=_claim_sort_key)

            latest_dt = group[-1].source_date or (group[-1].evidence_list[0].published_at if group[-1].evidence_list else None)
            earliest_dt = group[0].source_date or (group[0].evidence_list[0].published_at if group[0].evidence_list else None)
            latest_key = CutoffFilter._to_utc_naive(latest_dt)
            earliest_key = CutoffFilter._to_utc_naive(earliest_dt)

            if latest_key and earliest_key and latest_key > earliest_key:
                for c in group[:-1]:
                    c.status = ClaimStatus.SUPERSEDED
                    c.conflict_group_id = group_id
                group[-1].status = ClaimStatus.VALID
            elif group[-1].confidence > group[0].confidence:
                for c in group[:-1]:
                    c.status = ClaimStatus.SUPERSEDED
                    c.conflict_group_id = group_id
                group[-1].status = ClaimStatus.VALID
            else:
                for c in group:
                    c.status = ClaimStatus.CONFLICTED
                    c.conflict_group_id = group_id

        return claims
