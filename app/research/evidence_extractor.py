import re
from typing import List, Dict, Any, Optional
from app.research.models import Evidence


_DOMAIN_KEYWORDS = {
    "ABSENCES_HOME": ["injured", "injury", "miss", "unavailable", "ruled out", "doubt", "suspended", "sidelined", "fitness", "knock", "hamstring", "acl"],
    "ABSENCES_AWAY": ["injured", "injury", "miss", "unavailable", "ruled out", "doubt", "suspended", "sidelined", "fitness", "knock", "hamstring", "acl"],
    "MATCH_IDENTITY": ["vs", "versus", "kick-off", "kickoff", "stadium", "venue", "scheduled", "round", "matchday", "referee", "fixture", "derby"],
    "FORM_HOME": ["win", "won", "loss", "lost", "draw", "drew", "streak", "form", "unbeaten", "scored", "conceded", "points", "recent"],
    "FORM_AWAY": ["win", "won", "loss", "lost", "draw", "drew", "streak", "form", "unbeaten", "scored", "conceded", "points", "recent"],
    "STATISTICS": ["xg", "possession", "shots", "corners", "goals", "clean sheet", "pass accuracy", "tackles", "cards", "stats", "average"],
    "HEAD_TO_HEAD": ["head to head", "h2h", "previous meeting", "last meeting", "historic", "against each other", "record"],
    "EXPECTED_LINEUPS": ["lineup", "predicted", "starting xi", "formation", "probable", "squad", "bench", "xi", "4-3-3", "4-2-3-1", "3-5-2"],
    "WEATHER": ["weather", "rain", "temperature", "degrees", "celsius", "wind", "pitch", "forecast", "condition", "humidity", "storm"],
}


class EvidenceExtractor:
    def extract_evidence(self, doc: Dict[str, Any], domain: str) -> List[Evidence]:
        text = doc.get("text", "")
        url = doc.get("url", "")
        pub_at = doc.get("published_at")
        retrieved_at = doc.get("retrieved_at")
        canonical_url = doc.get("canonical_url") or url
        content_hash = doc.get("content_hash")
        doc_id = doc.get("document_id")

        if not text:
            return []

        evidence_list = []
        sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+|\n+', text) if len(s.strip()) > 15]
        keywords = _DOMAIN_KEYWORDS.get(domain, [])

        for sent in sentences:
            sent_lower = sent.lower()
            if keywords:
                if any(kw in sent_lower for kw in keywords):
                    evidence_list.append(Evidence(
                        source_url=url,
                        text_fragment=sent,
                        document_id=doc_id,
                        published_at=pub_at,
                        retrieved_at=retrieved_at,
                        canonical_url=canonical_url,
                        content_hash=content_hash,
                        domain=domain
                    ))
            else:
                evidence_list.append(Evidence(
                    source_url=url,
                    text_fragment=sent,
                    document_id=doc_id,
                    published_at=pub_at,
                    retrieved_at=retrieved_at,
                    canonical_url=canonical_url,
                    content_hash=content_hash,
                    domain=domain
                ))

        if not evidence_list and sentences:
            first_fragment = " ".join(sentences[:3])
            evidence_list.append(Evidence(
                source_url=url,
                text_fragment=first_fragment[:500],
                document_id=doc_id,
                published_at=pub_at,
                retrieved_at=retrieved_at,
                canonical_url=canonical_url,
                content_hash=content_hash,
                domain=domain
            ))

        return evidence_list
