from typing import List, Dict, Any

class ConflictDetector:
    @staticmethod
    def detect_conflicts(claims: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        conflicts = []
        subjects = {}

        for claim in claims:
            subj = claim.get("subject")
            pred = claim.get("predicate")
            obj = claim.get("object") or claim.get("normalized_value")
            c_id = claim.get("id") or claim.get("claim_id")

            key = (subj, pred)
            if key not in subjects:
                subjects[key] = []
            subjects[key].append({"value": str(obj).lower(), "claim_id": c_id, "claim": claim})

        for (subj, pred), entries in subjects.items():
            if len(entries) > 1:
                vals = set(e["value"] for e in entries)
                if len(vals) > 1:
                    conflicts.append({
                        "type": "conflicting_evidence",
                        "severity": "HIGH",
                        "description": f"Rozpor pro {subj} -> {pred}: hodnoty [{', '.join(vals)}]",
                        "claim_ids": [e["claim_id"] for e in entries if e["claim_id"] is not None],
                        "requires_research": True
                    })
        return conflicts
