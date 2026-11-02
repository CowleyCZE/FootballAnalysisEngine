"""Běh M975: AI použila ~14 let starý důkaz a v kontextu zůstával UI šum ze starší (znovu připojené) evidence."""
from datetime import datetime, timezone

from app.ai.context_builder import ContextBuilder

NOW = datetime(2026, 10, 31, tzinfo=timezone.utc)


def _claim(cid, *evidence):
    return {"claim_id": cid, "predicate": "p", "confidence": 0.5, "evidence": list(evidence)}


def _ev(eid, published_at, text="Slovácko přivítá v sobotu Teplice na domácím stadionu."):
    return {"evidence_id": eid, "published_at": published_at, "text_fragment": text}


def test_stale_and_boilerplate_evidence_are_dropped():
    claims = [
        _claim(1, _ev(10, "2012-08-01T00:00:00+00:00")),                       # ~14 let -> pryč, claim také
        _claim(2, _ev(11, "2012-08-01T00:00:00+00:00"), _ev(12, "2026-10-20T00:00:00+00:00")),
        _claim(3, _ev(13, None)),                                              # bez data se nechá
        _claim(4, _ev(14, "2026-10-20T00:00:00+00:00",
                      "Vámi zvolené nastavení neobsahuje souhlas se zobrazováním cílené reklamy. Vyberte prosím znovu")),
        _claim(5, _ev(15, "2026-10-20T00:00:00+00:00", "Facebook akademie Instagram akademie")),
    ]
    kept = ContextBuilder._drop_stale_evidence(claims, 730, now=NOW)
    assert [c["claim_id"] for c in kept] == [2, 3]
    assert [e["evidence_id"] for e in kept[0]["evidence"]] == [12]
    assert [e["evidence_id"] for e in kept[1]["evidence"]] == [13]
