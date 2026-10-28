from typing import List
import os
from datetime import datetime
from app.research.models import Claim, ClaimStatus
from app.research.cutoff_filter import CutoffFilter

TIME_SENSITIVE_PREDICATES = {
    "availability_status", "absence_report", "match_identity", "team_form",
    "has_absence", "is_injured", "is_suspended", "is_doubtful", "current_form",
    "expected_lineup", "lineup_status", "recent_results"
}

# TODO 11.10: dokument bez data publikace se u časově citlivých tvrzení (zranění, sestavy, forma,
# motivace, únava) nepoužije vůbec – nelze vyloučit informaci po cutoffu ani zastaralou. Statické
# domény (H2H, rivalita, profil týmu) projdou se sníženou důvěryhodností.
UNDATED_REJECT_EXTRA_PREDICATES = {"motivation_context", "fatigue_context"}
UNDATED_EXEMPT_PREDICATES = set()


def undated_policy() -> str:
    """`reject` (výchozí) nebo `allow` (staré chování, jen pro diagnostiku): FAE_UNDATED_POLICY."""
    value = (os.getenv("FAE_UNDATED_POLICY", "reject") or "reject").strip().lower()
    return "allow" if value == "allow" else "reject"


def source_weight(authority: float) -> float:
    """Váha zdroje 0.5–1.0 z autority registru (official 1.0, major_news 0.9, aggregator 0.75, unknown 0.6)."""
    try:
        a = max(0.0, min(1.0, float(authority)))
    except (TypeError, ValueError):
        a = 0.0
    return round(0.5 + 0.5 * a, 4)


class ClaimValidator:
    def apply_source_weights(self, claims: List[Claim], registry=None) -> List[Claim]:
        """Zvýší váhu oficiálních/datovaných zdrojů (klub, liga, statistický provider) proti agregátorům –
        důvěryhodnost se násobí váhou nejlepšího zdroje mezi důkazy tvrzení (TODO 11.10, bod 3)."""
        if os.getenv("FAE_SOURCE_WEIGHTING", "1") == "0":
            return claims
        if registry is None:
            from app.search.source_registry import SearchSourceRegistry
            registry = SearchSourceRegistry()
        for claim in claims:
            if claim.status == ClaimStatus.REJECTED or not claim.evidence_list:
                continue
            best = max(registry.get_authority(ev.source_url or "") for ev in claim.evidence_list)
            claim.confidence = round(float(claim.confidence or 0.0) * source_weight(best), 4)
        return claims

    def validate_claims(self, claims: List[Claim], cutoff_at: datetime) -> List[Claim]:
        validated = []
        for claim in claims:
            if not claim.evidence_list:
                claim.status = ClaimStatus.REJECTED
                validated.append(claim)
                continue

            is_time_sensitive = (
                claim.predicate in TIME_SENSITIVE_PREDICATES
                or "absence" in claim.predicate
                or "form" in claim.predicate
                or "lineup" in claim.predicate
                or "status" in claim.predicate
            )

            # Check claim's own source_date against cutoff
            if claim.source_date:
                passed, reason = CutoffFilter.validate(claim.source_date, cutoff_at, policy="strict_exclude")
                if not passed:
                    claim.status = ClaimStatus.REJECTED
                    validated.append(claim)
                    continue

            # Check all attached evidence published_at against cutoff
            reject_undated = (
                undated_policy() == "reject"
                and claim.predicate not in UNDATED_EXEMPT_PREDICATES
                and (is_time_sensitive or claim.predicate in UNDATED_REJECT_EXTRA_PREDICATES)
            )
            valid_ev = True
            for ev in claim.evidence_list:
                passed, reason = CutoffFilter.validate(ev.published_at, cutoff_at, policy="unverified_date")
                if not passed:
                    valid_ev = False
                    break
                if reason == "UNVERIFIED_DATE":
                    if reject_undated:
                        valid_ev = False
                        break
                    # Keep otherwise relevant official pages usable, but make
                    # the uncertainty visible to the AI/audit layers.
                    claim.confidence = max(0.0, float(claim.confidence or 0.0) * 0.65)

            if not valid_ev:
                claim.status = ClaimStatus.REJECTED
            else:
                claim.status = ClaimStatus.VALID

            validated.append(claim)
        return validated
