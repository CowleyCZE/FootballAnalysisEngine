import re
from typing import List, Dict, Any
from app.research.models import Claim, Evidence, ClaimStatus, AbsenceStatus

class ClaimBuilder:
    def build_claims_from_evidence(self, evidence_list: List[Evidence], team_name: str) -> List[Claim]:
        claims = []

        for ev in evidence_list:
            text = ev.text_fragment
            status = AbsenceStatus.UNKNOWN
            if any(w in text.lower() for w in ["ruled out", "will miss", "injured", "injury"]):
                status = AbsenceStatus.UNAVAILABLE
            elif "doubt" in text.lower() or "assessed" in text.lower():
                status = AbsenceStatus.DOUBTFUL

            names = re.findall(r'\b[A-Z][a-z]+\s+[A-Z][a-z]+\b', text)
            for name in names:
                if team_name.lower() in name.lower():
                    continue

                claim = Claim(
                    subject=name,
                    predicate="availability_status",
                    object_value=status.value,
                    normalized_value=f"{name}:{status.value}",
                    evidence_list=[ev],
                    source_date=ev.published_at,
                    status=ClaimStatus.CANDIDATE
                )
                claims.append(claim)

        return claims
