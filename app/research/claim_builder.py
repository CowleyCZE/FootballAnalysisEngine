import re
from typing import List, Dict, Any, Optional
from app.research.models import Claim, Evidence, ClaimStatus, AbsenceStatus

# Jména s diakritikou (TODO 3.4): „Patrik Schick“, „Tomáš Hořavá“, „Šimeček Jan“
_UP = "A-ZÁČĎÉĚÍŇÓŘŠŤÚŮÝŽ"
_LOW = "a-záčďéěíňóřšťúůýž"
NAME_RE = re.compile(rf"\b[{_UP}][{_LOW}]+\s+[{_UP}][{_LOW}]+\b")

_UNAVAILABLE_WORDS = ["ruled out", "will miss", "injured", "injury", "sidelined",
                      "zraněn", "zranil", "chybí", "chybět", "chyběl", "nenastoup", "neodehraj", "marod", "nebude k dispozici"]
_DOUBTFUL_WORDS = ["doubt", "assessed", "questionable", "pochybn", "otázn", "nejist", "posuzuje"]
_SUSPENDED_WORDS = ["suspended", "suspend", "distanc", "zastaven", "trest"]


class ClaimBuilder:
    def build_claims_from_evidence(self, evidence_list: List[Evidence], team_name: str) -> List[Claim]:
        claims = []

        for ev in evidence_list:
            domain = getattr(ev, "domain", None) or "GENERAL"
            text = ev.text_fragment

            if "ABSENCES" in domain:
                status = AbsenceStatus.UNKNOWN
                if any(w in text.lower() for w in _UNAVAILABLE_WORDS):
                    status = AbsenceStatus.UNAVAILABLE
                elif any(w in text.lower() for w in _DOUBTFUL_WORDS):
                    status = AbsenceStatus.DOUBTFUL
                elif any(w in text.lower() for w in _SUSPENDED_WORDS):
                    status = AbsenceStatus.SUSPENDED

                names = NAME_RE.findall(text)
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

            elif domain.startswith("TEAM_PROFILE_"):
                claims.append(Claim(
                    subject=team_name,
                    predicate="team_profile_fact",
                    object_value=text,
                    normalized_value=f"{team_name}:profile:{text[:80]}",
                    evidence_list=[ev],
                    source_date=ev.published_at,
                    status=ClaimStatus.CANDIDATE,
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

            elif domain == "REFEREE":
                predicate, subject = "referee_profile", "match_referee"
                claims.append(Claim(subject=subject, predicate=predicate, object_value=text,
                                     normalized_value=f"referee:{text[:60]}", evidence_list=[ev],
                                     source_date=ev.published_at, status=ClaimStatus.CANDIDATE))

            elif domain == "RIVALRY":
                claims.append(Claim(subject="match_rivalry", predicate="rivalry_context",
                                     object_value=text, normalized_value=f"rivalry:{text[:60]}",
                                     evidence_list=[ev], source_date=ev.published_at,
                                     status=ClaimStatus.CANDIDATE))

            elif domain == "STYLE_MATCHUP":
                claims.append(Claim(subject="match_style", predicate="style_matchup",
                                     object_value=text, normalized_value=f"style:{text[:60]}",
                                     evidence_list=[ev], source_date=ev.published_at,
                                     status=ClaimStatus.CANDIDATE))

            elif domain.startswith("MOTIVATION_"):
                claims.append(Claim(subject=team_name, predicate="motivation_context",
                                     object_value=text, normalized_value=f"{team_name}:motivation:{text[:50]}",
                                     evidence_list=[ev], source_date=ev.published_at,
                                     status=ClaimStatus.CANDIDATE))

            elif domain.startswith("TRAVEL_FATIGUE_"):
                claims.append(Claim(subject=team_name, predicate="fatigue_context",
                                     object_value=text, normalized_value=f"{team_name}:fatigue:{text[:50]}",
                                     evidence_list=[ev], source_date=ev.published_at,
                                     status=ClaimStatus.CANDIDATE))

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
