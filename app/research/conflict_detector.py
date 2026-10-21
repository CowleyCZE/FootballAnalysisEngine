import uuid
from typing import Any, List, Dict, Tuple
from datetime import datetime, timezone
from app.research.models import Claim, ClaimStatus
from app.research.cutoff_filter import CutoffFilter


# Only predicates where one subject can hold a single value at a time. Free-text
# predicates (team_profile_fact, team_form, general_fact...) legitimately carry many
# different sentences and must not be treated as contradictions.
EXCLUSIVE_PREDICATES = {"availability_status", "availability", "status", "is_injured", "is_suspended"}


class ConflictDetector:
    @staticmethod
    def detect_conflicts(claims: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Audit pohled na stejná pravidla (TODO 4.3): claimy jako dicty z DB -> seznam nálezů.
        Používá stejnou množinu exkluzivních predikátů a stejné normalizované klíče (subjekt, predikát)
        jako `detect_and_resolve`; zde se ale nic nemění, jen se hlásí rozpory."""
        grouped: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
        for claim in claims:
            pred = str(claim.get("predicate") or "").lower().strip()
            if pred not in EXCLUSIVE_PREDICATES:
                continue
            subj = str(claim.get("subject") or "").lower().strip()
            obj = claim.get("object") or claim.get("object_value") or claim.get("normalized_value")
            grouped.setdefault((subj, pred), []).append({
                "value": str(obj).lower().strip(),
                "claim_id": claim.get("id") or claim.get("claim_id"),
                "subject_raw": claim.get("subject"),
                "predicate_raw": claim.get("predicate"),
            })

        conflicts: List[Dict[str, Any]] = []
        for (subj, pred), entries in grouped.items():
            values = {e["value"] for e in entries}
            if len(entries) > 1 and len(values) > 1:
                conflicts.append({
                    "type": "conflicting_evidence",
                    "severity": "HIGH",
                    "description": f"Rozpor pro {entries[0]['subject_raw']} -> {entries[0]['predicate_raw']}: hodnoty [{', '.join(sorted(values))}]",
                    "claim_ids": [e["claim_id"] for e in entries if e["claim_id"] is not None],
                    "requires_research": True,
                })
        return conflicts

    def detect_and_resolve(self, claims: List[Claim]) -> List[Claim]:
        grouped: Dict[Tuple[str, str], List[Claim]] = {}

        for c in claims:
            if c.predicate.lower().strip() not in EXCLUSIVE_PREDICATES:
                continue
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
