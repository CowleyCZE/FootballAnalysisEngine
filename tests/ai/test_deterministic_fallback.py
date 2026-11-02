"""TODO 11.29: deterministický závěr z tipu a statistik, když AI nevrátí použitelný výstup (běh M1_53d1)."""
import httpx
import pytest

from app.ai.client import OllamaClient
from app.ai.context_builder import ContextBuilder
from app.audit.auditor import AdversarialAuditor
from app.workers.ai_worker import AIWorker

CUTOFF = "2026-11-02T00:59:31+00:00"


def _snap(team, metric, value, sample, coverage):
    return {"team": team, "metric": metric, "value": value, "sample_size": sample, "coverage": coverage}


def _context(claims=None, prior_only=False, with_prediction=True):
    statistics = {
        "snapshots": [
            _snap("home", "form_points", 4.0, 5, 0.55),
            _snap("away", "form_points", 8.0, 5, 0.55),
            _snap("home", "xgd_ewma", -0.76, 8, 0.8),
            _snap("away", "xgd_ewma", -0.25, 9, 0.9),
            _snap("home", "xg_elo", 1454.41, 12, 1.0),
            _snap("away", "xg_elo", 1495.45, 12, 1.0),
            # bez vzorku se do závěru nedostane
            _snap("home", "npxg_for_ewma", None, 0, 0.0),
        ]
    }
    if with_prediction:
        statistics["prediction"] = {
            "predicted_score": "1-1",
            "expected_goals": {"home": 1.11, "away": 1.63},
            "probabilities_1x2": {"home_win": 0.261, "draw": 0.247, "away_win": 0.492},
            "top_scores": {"1-1": 0.117, "0-1": 0.105, "1-2": 0.095},
            "prior_only": prior_only,
        }
    return {
        "match": {"match_id": 1, "home_team": "Zlín", "away_team": "SK Sigma Olomouc",
                  "scheduled_at": "2026-10-24T13:00:00+00:00", "data_cutoff_at": CUTOFF},
        "statistics": statistics,
        "claims": claims or [],
        "conflicts": [],
        "data_quality": {"score": 0.7, "source_count": 3, "independent_sources": 2, "official_sources": 0,
                         "conflicts": 0, "freshness_score": 0.5, "missing_data": []},
    }


def test_deterministic_result_uses_tip_and_snapshots():
    result = AIWorker._deterministic_result(1, _context(), ["Lokální AI služba neposkytla použitelný výstup"])
    assert result is not None
    assert result["status"] == "complete"
    assert result["composition"] == "deterministic_statistical"
    assert result["llm_provider"] == "deterministic"
    # key_factors bez důkazů by audit označil jako missing_evidence (HIGH) -> musí být prázdné
    assert result["key_factors"] == []
    conclusion = result["conclusion"]
    assert "1:1" in conclusion
    assert "Zlín 4 b. z 5 zápasů" in conclusion
    assert "SK Sigma Olomouc 8 b. z 5 zápasů" in conclusion
    assert "-0,76" in conclusion and "-0,25" in conclusion
    assert "1454" in conclusion and "1495" in conclusion
    assert "npxg" not in conclusion.lower()
    assert any("top 3" in f and "1:1 (11,7 %)" in f for f in result["statistical_factors"])
    assert result["ai_failure_reasons"] == ["Lokální AI služba neposkytla použitelný výstup"]
    assert any("AI vysvětlení není k dispozici" in u for u in result["uncertainties"])


def test_low_xg_coverage_is_reported():
    result = AIWorker._deterministic_result(1, _context(), [])
    assert "Pokrytí xG daty je nižší u" in result["conclusion"]
    assert "Zlín (55 %)" in result["conclusion"]


def test_no_usable_tip_means_no_deterministic_result():
    assert AIWorker._deterministic_result(1, _context(prior_only=True), []) is None
    assert AIWorker._deterministic_result(1, _context(with_prediction=False), []) is None


def test_deterministic_fallback_can_be_disabled(monkeypatch):
    monkeypatch.setenv("FAE_AI_DETERMINISTIC_FALLBACK", "0")
    assert AIWorker._deterministic_result(1, _context(), []) is None


def _payload():
    return {"match_id": 1, "data_cutoff_at": CUTOFF, "match": {"match_id": 1}, "db_path": ":memory:"}


def test_execute_without_claims_falls_back_to_tip(monkeypatch):
    monkeypatch.setattr(ContextBuilder, "build_context", lambda self, **kw: _context())
    result = AIWorker.execute(_payload())
    assert result["status"] == "complete"
    assert result["composition"] == "deterministic_statistical"


def test_execute_with_failing_llm_falls_back_to_tip(monkeypatch):
    claim = {"claim_id": 10, "subject": "Zlín", "predicate": "rivalry_context", "object": "Zlín hraje s Olomoucí",
             "confidence": 0.6, "status": "VALID",
             "evidence": [{"evidence_id": 501, "excerpt": "Zlín hraje s Olomoucí", "published_at": None}]}
    monkeypatch.setattr(ContextBuilder, "build_context", lambda self, **kw: _context(claims=[claim]))

    def broken_generate(self, prompt, system_prompt=None, require_json=True):
        raise RuntimeError("Ollama API request failed after 2 retries: timed out")

    monkeypatch.setattr(OllamaClient, "generate", broken_generate)
    result = AIWorker.execute(_payload())
    assert result["status"] == "complete"
    assert result["composition"] == "deterministic_statistical"
    assert "timed out" in " ".join(result["ai_failure_reasons"])


def test_truncated_json_is_retried_then_falls_back(monkeypatch):
    claim = {"claim_id": 10, "subject": "Zlín", "predicate": "rivalry_context", "object": "Zlín hraje s Olomoucí",
             "confidence": 0.6, "status": "VALID",
             "evidence": [{"evidence_id": 501, "excerpt": "Zlín hraje s Olomoucí", "published_at": None}]}
    monkeypatch.setattr(ContextBuilder, "build_context", lambda self, **kw: _context(claims=[claim]))
    prompts = []

    def truncated(self, prompt, system_prompt=None, require_json=True):
        prompts.append(prompt)
        return '{\n  "conclusion": "Zlín'

    monkeypatch.setattr(OllamaClient, "generate", truncated)
    monkeypatch.setenv("FAE_AI_REPAIR_RETRIES", "1")
    result = AIWorker.execute(_payload())
    assert len(prompts) == 2 and "KRATŠÍ a úplný JSON" in prompts[1]
    assert result["composition"] == "deterministic_statistical"
    assert "JSON Decode Error" in " ".join(result["ai_failure_reasons"])
    assert "začátek" in " ".join(result["ai_failure_reasons"])


def test_ollama_client_reports_length_cutoff(monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"response": '{"conclusion": "abc', "done_reason": "length"}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def post(self, url, json=None):
            return FakeResponse()

    monkeypatch.setattr(httpx, "Client", FakeClient)
    client = OllamaClient(max_retries=2)
    with pytest.raises(RuntimeError, match="done_reason=length"):
        client.generate("x")


def test_audit_keeps_warning_for_deterministic_conclusion(tmp_path):
    result = AIWorker._deterministic_result(1, _context(), ["Lokální AI služba neposkytla použitelný výstup"])
    auditor = AdversarialAuditor(db_path=str(tmp_path / "audit.db"), log_dir=str(tmp_path / "logs"))
    audit = auditor.audit(match_id=1, ai_run_id="x", ai_analysis=result, claims=[], statistics={},
                          data_cutoff_at=CUTOFF)
    issue_types = [i["type"] for i in audit["issues"]]
    assert "ai_analysis_unavailable" in issue_types
    assert "missing_evidence" not in issue_types
    assert audit["audit_score"] == 1.0
    assert audit["status"] == "AUDIT_COMPLETE"
