"""TODO 11.27 (běh M976_f6a9): (1) RIVALRY/H2H berou jen dokumenty, které zmiňují OBA týmy (derby Slovan – Trnava
prošlo, protože stačil jeden tým); (2) faktor AI nesmí být opsané označení claimu „Tým:profile:…“."""
import json

from app.research.evidence_extractor import EvidenceExtractor
from app.workers.ai_worker import AIWorker

TEAMS = ["Zlín", "Slovácko"]


def _doc(text, title=""):
    return {"text": text, "title": title, "url": "https://example.test/derby", "document_id": 1}


def test_rivalry_requires_both_teams():
    both = "Zlín porazil v derby Slovácko 1:0. Derby bývá vyhrocené."
    one = "Slovácko před derby trénuje. Derby je vždycky výzva pro celý tým."
    assert EvidenceExtractor().extract_evidence(_doc(both), "RIVALRY", entities=TEAMS)
    assert EvidenceExtractor().extract_evidence(_doc(one), "RIVALRY", entities=TEAMS) == []


def test_head_to_head_requires_both_teams():
    one = "Slovácko má bilanci vzájemných zápasů výbornou."
    assert EvidenceExtractor().extract_evidence(_doc(one), "HEAD_TO_HEAD", entities=TEAMS) == []


def test_team_domains_still_need_only_their_team():
    text = "Slovácko hraje v dobré formě, vyhrálo poslední zápas."
    assert EvidenceExtractor().extract_evidence(_doc(text), "FORM_AWAY", entities=["Slovácko"])


def test_pair_domain_without_entities_is_unchanged():
    assert EvidenceExtractor().extract_evidence(_doc("Derby bývá vyhrocené."), "RIVALRY")


CONTEXT = {
    "match": {"home_team": "Zlín", "away_team": "Slovácko", "scheduled_at": "2026-11-07T14:00:00+00:00"},
    "data_quality": {"score": 0.7, "source_count": 2, "independent_sources": 2, "official_sources": 0,
                     "conflicts": 0, "freshness_score": 0.5, "missing_data": []},
    "claims": [
        {"claim_id": 1, "subject": "Slovácko", "predicate": "profile", "object": "home form is very poor",
         "evidence": [{"evidence_id": 7547, "excerpt": "Slovácko's home form is very poor: 0 wins, 3 draws, 5 losses."}]},
    ],
    "conflicts": [],
}


def _raw(factors):
    return json.dumps({"conclusion": "Slovácko má doma slabou formu.", "key_factors": factors, "uncertainties": []})


def test_raw_claim_label_is_stripped_and_own_wording_kept():
    res, err = AIWorker._compose_result(_raw([
        {"factor": "Slovácko:profile:Slovácko's home form is very poor with 0 wins", "importance": 1.0, "evidence_ids": [7547]},
        {"factor": "Slovácko doma nevyhrálo, 3 remízy a 5 proher", "importance": 0.8, "evidence_ids": [7547]},
    ]), 976, CONTEXT)
    assert res is not None, err
    assert [f.factor for f in res.key_factors] == [
        "Slovácko's home form is very poor with 0 wins", "Slovácko doma nevyhrálo, 3 remízy a 5 proher"]
    assert any("bez označení" in u for u in res.uncertainties)


def test_label_with_too_short_remainder_leads_to_rejection_with_reason():
    res, err = AIWorker._compose_result(_raw([
        {"factor": "Slovácko:profile:poor", "importance": 1.0, "evidence_ids": [7547]},
    ]), 976, CONTEXT)
    assert res is None and "klíčový faktor" in err and "opsané označení" in err
