import json

from app.ai.client import OllamaClient
from app.ai.schemas import AnalysisResult
from app.ai.validator import AIValidator
from app.research.source_selector import is_blocked_source
from app.workers.ai_worker import AIWorker


CTX = {
    "data_quality": {"score": 0.5, "source_count": 3},
    "claims": [{"claim_id": 1, "subject": "Sparta", "predicate": "form", "object": "dobrý",
                 "evidence": [{"evidence_id": 100}, {"evidence_id": 101}]}],
    "conflicts": [{"subject": "Sparta", "predicate": "form", "detail": "rozpor"}],
}


def _compose(payload, ctx=CTX):
    raw = payload if isinstance(payload, str) else json.dumps(payload)
    return AIWorker._compose_result(raw, 593, ctx)


def test_compose_uses_system_fields_not_ai_fields():
    res, err = _compose({"match_id": 1, "status": "complete", "conclusion": "Shrnutí zápasu.",
                         "key_factors": [{"factor": "forma týmu", "importance": 0.5, "evidence_ids": [100]}],
                         "data_quality": {"score": 0.99}, "home_team_analysis": {"strengths": ["x"]}})
    assert res is not None, err
    assert res.match_id == 593
    assert res.data_quality.score == 0.5
    assert res.home_team_analysis is None and res.away_team_analysis is None
    assert res.conflicts_noted and "Sparta" in res.conflicts_noted[0]


def test_compose_missing_conclusion_is_never_fabricated():
    res, err = _compose({"key_factors": []})
    assert res is None and err
    res, err = _compose({"conclusion": "   "})
    assert res is None


def test_compose_drops_invented_evidence_ids():
    res, err = _compose({"conclusion": "x", "key_factors": [
        {"factor": "dobrý", "importance": 0.7, "evidence_ids": [100, 999]},
        {"factor": "vymyšlený", "importance": 0.9, "evidence_ids": [555]},
        {"factor": "bez důkazu", "importance": 0.4, "evidence_ids": []},
    ]})
    assert res is not None, err
    assert [f.factor for f in res.key_factors] == ["dobrý"]
    assert res.key_factors[0].evidence_ids == [100]
    assert any("999" in u for u in res.uncertainties)
    assert any("vymyšlený" in u for u in res.uncertainties)
    assert any("bez důkazu" in u for u in res.uncertainties)


def test_compose_conclusion_without_grounded_factor_is_rejected():
    res, err = _compose({"conclusion": "Slavia je obhájce.", "key_factors": []})
    assert res is None and "podložen" in err
    res, err = _compose({"conclusion": "x", "key_factors": [{"factor": "f", "importance": 0.5, "evidence_ids": [999]}]})
    assert res is None


def test_compose_invalid_json_and_insufficient_status():
    res, err = _compose("not json")
    assert res is None and err
    res, err = _compose({"status": "insufficient_data", "conclusion": "x"})
    assert res is None


def test_worker_sends_small_schema(monkeypatch):
    from app.ai.schemas import AIOutput
    props = AIOutput.model_json_schema()["properties"]
    assert set(props) == {"conclusion", "key_factors", "uncertainties"}


def test_client_sends_schema_as_format(monkeypatch):
    sent = {}

    class FakeResp:
        def raise_for_status(self): pass
        def json(self): return {"response": "{}"}

    class FakeHttp:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def post(self, url, json=None):
            sent.update(json)
            return FakeResp()

    monkeypatch.setattr("app.ai.client.httpx.Client", FakeHttp)
    client = OllamaClient()
    client.generate("x")
    assert sent["format"] == "json"
    client.json_schema = AnalysisResult.model_json_schema()
    client.generate("x")
    assert isinstance(sent["format"], dict) and "match_id" in sent["format"]["properties"]


def test_cycling_sites_are_blocked_but_football_is_not():
    assert is_blocked_source("https://www.sparta-cycling.cz/clanek")
    assert is_blocked_source("https://example.cz/a", title="Cyklistika: výsledky závodu")
    assert not is_blocked_source("https://www.sparta.cz/clanek", title="Sparta vyhrála derby")
