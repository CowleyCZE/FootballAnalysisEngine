import re
from typing import List, Dict, Any, Optional
from app.research.models import Claim, Evidence, ClaimStatus, AbsenceStatus


class ClaimBuilder:
    def build_claims_from_evidence(self, evidence_list: List[Evidence], team_name: str) -> List[Claim]:
        claims = []

        for ev in evidence_list:
            domain = getattr(ev, "domain", None) or "GENERAL"
            text = ev.text_fragment

            if "ABSENCES" in domain:
                status = AbsenceStatus.UNKNOWN
                if any(w in text.lower() for w in ["ruled out", "will miss", "injured", "injury", "sidelined"]):
                    status = AbsenceStatus.UNAVAILABLE
                elif any(w in text.lower() for w in ["doubt", "assessed", "questionable"]):
                    status = AbsenceStatus.DOUBTFUL
                elif "suspended" in text.lower():
                    status = AbsenceStatus.SUSPENDED

                names = re.findall(r'\b[A-Z][a-z]+\s+[A-Z][a-z]+\b', text)
                found_names = [n for n in names if team_name.lower() not in n.lower()]
                if found_names:
                    for name in found_names:
                        claims.append(Claim(
                            subject=name,
                            predicate="availability_status",
                            object_value=status.value,
                            normalized_value=f"{name}:{status.value}",
                            evidence_list=[ev],
                            source_date=ev.published_at,
                            status=ClaimStatus.CANDIDATE
                        ))
                else:
                    claims.append(Claim(
                        subject=f"{team_name}_absences",
                        predicate="absence_report",
                        object_value=text,
                        normalized_value=f"{team_name}:absences:{text[:30]}",
                        evidence_list=[ev],
                        source_date=ev.published_at,
                        status=ClaimStatus.CANDIDATE
                    ))

            elif domain == "MATCH_IDENTITY":
                claims.append(Claim(
                    subject=f"{team_name}_match",
                    predicate="match_identity",
                    object_value=text,
                    normalized_value=f"match_identity:{text[:40]}",
                    evidence_list=[ev],
                    source_date=ev.published_at,
                    status=ClaimStatus.CANDIDATE
                ))

            elif "FORM" in domain:
                claims.append(Claim(
                    subject=team_name,
                    predicate="team_form",
                    object_value=text,
                    normalized_value=f"{team_name}:form:{text[:30]}",
                    evidence_list=[ev],
                    source_date=ev.published_at,
                    status=ClaimStatus.CANDIDATE
                ))

            elif domain == "STATISTICS":
                claims.append(Claim(
                    subject=team_name,
                    predicate="team_statistics",
                    object_value=text,
                    normalized_value=f"{team_name}:stats:{text[:30]}",
                    evidence_list=[ev],
                    source_date=ev.published_at,
                    status=ClaimStatus.CANDIDATE
                ))

            elif domain == "HEAD_TO_HEAD":
                claims.append(Claim(
                    subject="head_to_head",
                    predicate="h2h_record",
                    object_value=text,
                    normalized_value=f"h2h:{text[:40]}",
                    evidence_list=[ev],
                    source_date=ev.published_at,
                    status=ClaimStatus.CANDIDATE
                ))

            elif domain == "EXPECTED_LINEUPS":
                claims.append(Claim(
                    subject=team_name,
                    predicate="expected_lineup",
                    object_value=text,
                    normalized_value=f"{team_name}:lineup:{text[:30]}",
                    evidence_list=[ev],
                    source_date=ev.published_at,
                    status=ClaimStatus.CANDIDATE
                ))

            elif domain == "WEATHER":
                claims.append(Claim(
                    subject="match_weather",
                    predicate="weather_condition",
                    object_value=text,
                    normalized_value=f"weather:{text[:30]}",
                    evidence_list=[ev],
                    source_date=ev.published_at,
                    status=ClaimStatus.CANDIDATE
                ))

            else:
                claims.append(Claim(
                    subject=team_name or "match_general",
                    predicate="general_fact",
                    object_value=text,
                    normalized_value=f"general:{text[:30]}",
                    evidence_list=[ev],
                    source_date=ev.published_at,
                    status=ClaimStatus.CANDIDATE
                ))

        return claims
