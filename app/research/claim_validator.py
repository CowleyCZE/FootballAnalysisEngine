from typing import List
import os
from datetime import datetime
from app.research.models import Claim, ClaimStatus
from app.research.cutoff_filter import CutoffFilter
from app.research.staleness import STALE_REJECTED, is_stale

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

# TODO 11.20-d: u encyklopedií (Wikipedie) je `datePublished` datum vzniku článku, ne aktuálnosti obsahu
# (stránka se průběžně přepisuje) – pro časově citlivá tvrzení se jejich datum nepovažuje za ověřené.
ENCYCLOPEDIC_DOMAINS = ("wikipedia.org", "wikidata.org", "wikimedia.org", "wiktionary.org")


def is_encyclopedic_source(url: str) -> bool:
    from urllib.parse import urlparse

    host = (urlparse(url or "").hostname or "").lower()
    return any(host == d or host.endswith("." + d) for d in ENCYCLOPEDIC_DOMAINS)


# TODO 11.20-c (rozhodnuto: asistent, 29. 10. 2026): bezdatový časově citlivý důkaz z registrovaného statistického /
# agregátorského / oficiálního zdroje se přijme s `date_source=retrieved_at`, pokud byl stažen ≤ cutoff a
# nejvýše N dní před ním (výchozí 7, FAE_RETRIEVED_MAX_AGE_DAYS); důvěra ×0,5. Vypnutí FAE_RETRIEVED_AT_FALLBACK=0.
# Zpravodajství bez data, neznámé zdroje a encyklopedie se nepovolujou. Model tipu (absenční multiplikátor v
# research_context.py) zůstává přísný – bezdatová fakta do číselného tipu nevstupují.
RETRIEVED_AT_SOURCE_TYPES = {"statistical_provider", "aggregator", "official_club", "official_league"}
RETRIEVED_AT_CONFIDENCE = 0.5


def retrieved_at_fallback_enabled() -> bool:
    return os.getenv("FAE_RETRIEVED_AT_FALLBACK", "1").strip() != "0"


def retrieved_max_age_days() -> float:
    try:
        return max(0.0, float(os.getenv("FAE_RETRIEVED_MAX_AGE_DAYS", "7")))
    except ValueError:
        return 7.0


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
    @staticmethod
    def _retrieved_at_fallback_ok(ev, cutoff_at, registry=None) -> bool:
        """Bezdatový důkaz smí projít jen z registrovaného statistického/agregátorského/oficiálního zdroje,
        pokud byl skutečně stažen nejvýše RETRIEVED_MAX_AGE_DAYS před cutoffem a ne po něm.
        Datum publikace se nikdy nedomyslí; neznámé zdroje a encyklopedie se nepovolujou."""
        if not retrieved_at_fallback_enabled():
            return False
        url = getattr(ev, "source_url", "") or ""
        if is_encyclopedic_source(url):
            return False
        retrieved = CutoffFilter._to_utc_naive(getattr(ev, "retrieved_at", None))
        cutoff = CutoffFilter._to_utc_naive(cutoff_at)
        if retrieved is None or cutoff is None or retrieved > cutoff:
            return False
        if (cutoff - retrieved).total_seconds() > retrieved_max_age_days() * 86400:
            return False
        if registry is None:
            from app.search.source_registry import SearchSourceRegistry
            registry = SearchSourceRegistry()
        return registry.get_source_type(url) in RETRIEVED_AT_SOURCE_TYPES

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

    def validate_claims(self, claims: List[Claim], cutoff_at: datetime, registry=None) -> List[Claim]:
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
                if reject_undated and is_encyclopedic_source(getattr(ev, "source_url", "") or ""):
                    valid_ev = False
                    break
                passed, reason = CutoffFilter.validate(ev.published_at, cutoff_at, policy="unverified_date")
                if not passed:
                    valid_ev = False
                    break
                # TODO 11.35: absolutní horní mez stáří (365 dní časově senzitivné, 10 let statické).
                if is_stale(ev.published_at, cutoff_at, claim.predicate):
                    valid_ev = False
                    claim.reject_reason = STALE_REJECTED
                    break
                if reason == "UNVERIFIED_DATE":
                    if reject_undated:
                        if self._retrieved_at_fallback_ok(ev, cutoff_at, registry):
                            # TODO 11.20-c: skutečný čas stažení (≤ cutoff) je horní mez stáří obsahu.
                            if getattr(claim, "date_source", None) != "retrieved_at":
                                claim.date_source = "retrieved_at"
                                claim.confidence = max(0.0, float(claim.confidence or 0.0) * RETRIEVED_AT_CONFIDENCE)
                            continue
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
