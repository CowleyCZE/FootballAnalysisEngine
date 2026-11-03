"""TODO 11.35 – absolutn\u00ed horn\u00ed mez st\u00e1\u0159\u00ed d\u016fkaz\u016f podle dom\u00e9ny/predik\u00e1tu.

\u010casov\u011b senzitivn\u00ed dom\u00e9ny (sestavy, absence, forma, motivace, \u00fanava): max. 365 dn\u00ed.
Statick\u00e9 dom\u00e9ny (H2H, rivalita): max. 10 let (3 650 dn\u00ed = 87 600 h).
Star\u0161\u00ed z\u00e1znam je `STALE_REJECTED`. St\u00e1\u0159\u00ed se po\u010d\u00edt\u00e1 k cutoffu (ne k aktu\u00e1ln\u00edmu \u010dasu); d\u016fkaz bez data se zde
nehodnot\u00ed (ten \u0159e\u0161\u00ed undated policy), datum se nikdy nedom\u00fd\u0161l\u00ed.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

STALE_REJECTED = "STALE_REJECTED"
TIME_SENSITIVE_MAX_AGE_DAYS = 365
STATIC_MAX_AGE_DAYS = 3650

TIME_SENSITIVE_PREDICATES = frozenset({
    "availability_status", "absence_report", "has_absence", "is_injured", "is_suspended", "is_doubtful",
    "expected_lineup", "lineup_status", "team_form", "current_form", "recent_results",
    "motivation_context", "fatigue_context",
})
STATIC_PREDICATES = frozenset({"h2h_record", "rivalry_context"})


def max_age_days_for(predicate: Optional[str]) -> Optional[int]:
    """Limit st\u00e1\u0159\u00ed ve dnech pro predik\u00e1t; None = pro tento predik\u00e1t se absolutn\u00ed limit neuplat\u0148uje."""
    p = str(predicate or "")
    if p in STATIC_PREDICATES:
        return STATIC_MAX_AGE_DAYS
    if p in TIME_SENSITIVE_PREDICATES or any(k in p for k in ("absence", "lineup", "form", "injur", "suspen")):
        return TIME_SENSITIVE_MAX_AGE_DAYS
    return None


def _to_utc(value: Any) -> Optional[datetime]:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def is_stale(published_at: Any, reference_at: Any, predicate: Optional[str]) -> bool:
    """True, pokud je d\u016fkaz star\u0161\u00ed ne\u017e limit predik\u00e1tu k referen\u010dn\u00edmu \u010dasu (cutoff; bez n\u011bj now)."""
    limit = max_age_days_for(predicate)
    pub = _to_utc(published_at)
    if limit is None or pub is None:
        return False
    ref = _to_utc(reference_at) or datetime.now(timezone.utc)
    return (ref - pub).total_seconds() > limit * 86400
