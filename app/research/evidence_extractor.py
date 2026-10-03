import re
from typing import List, Dict, Any, Optional
from app.research.models import Evidence

class EvidenceExtractor:
    def extract_evidence(self, doc: Dict[str, Any], domain: str) -> List[Evidence]:
        text = doc.get("text", "")
        url = doc.get("url", "")
        pub_at = doc.get("published_at")
        doc_id = doc.get("document_id")

        evidence_list = []

        if domain in ["ABSENCES_HOME", "ABSENCES_AWAY"]:
            sentences = re.split(r'(?<=[.!?]) +', text)
            for sent in sentences:
                if any(w in sent.lower() for w in ["injured", "injury", "miss", "unavailable", "ruled out", "doubt"]):
                    evidence_list.append(Evidence(
                        source_url=url,
                        text_fragment=sent.strip(),
                        document_id=doc_id,
                        published_at=pub_at
                    ))

        return evidence_list
