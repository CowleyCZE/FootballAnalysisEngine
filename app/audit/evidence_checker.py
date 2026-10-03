from typing import List, Dict, Any

class EvidenceChecker:
    @staticmethod
    def check_ai_evidence(analysis_dict: Dict[str, Any], available_evidence_ids: List[int]) -> List[Dict[str, Any]]:
        issues = []
        key_factors = analysis_dict.get("key_factors", [])

        for factor in key_factors:
            ev_ids = factor.get("evidence_ids", [])
            factor_text = factor.get("factor", "")

            if not ev_ids:
                issues.append({
                    "type": "missing_evidence",
                    "severity": "HIGH",
                    "description": f"Klíčový faktor bez důkazu: '{factor_text}'",
                    "evidence_ids": [],
                    "requires_research": True
                })
            else:
                invalid_ids = [eid for eid in ev_ids if eid not in available_evidence_ids]
                if invalid_ids:
                    issues.append({
                        "type": "unsupported_claim",
                        "severity": "CRITICAL",
                        "description": f"Klíčový faktor odkázal na neexistující evidence_ids: {invalid_ids}",
                        "evidence_ids": invalid_ids,
                        "requires_research": True
                    })
        return issues
