import json
import os
from typing import Any, Dict

from app.ai.client import OllamaClient
from app.ai.context_builder import ContextBuilder
from app.ai.schemas import AnalysisResult
from app.ai.validator import AIValidator


class AIWorker:
    @staticmethod
    def execute(payload: Dict[str, Any]) -> Dict[str, Any]:
        match_id = int(payload.get("match_id"))
        statistics = payload.get("statistics") or {}
        claims = payload.get("claims") or []
        conflicts = payload.get("conflicts") or []
        match_info = payload.get("match") or {"match_id": match_id}

        context = ContextBuilder().build_context(
            match_info=match_info,
            claims=claims,
            statistics=statistics,
            conflicts=conflicts,
        )
        prompt = (
            "Analyze the football match using ONLY the supplied context. "
            "Do not invent facts, statistics, players, injuries, sources or evidence. "
            "Every key factor must reference evidence_ids that exist in the context. "
            "If data is insufficient, explicitly return status='insufficient_data'.\n\n"
            + json.dumps(context, ensure_ascii=False, indent=2)
        )
        client = OllamaClient(
            base_url=os.getenv("OLLAMA_URL", "http://127.0.0.1:11434"),
            model=os.getenv("OLLAMA_MODEL", "qwen2.5:7b"),
            temperature=float(os.getenv("OLLAMA_TEMPERATURE", "0.1")),
            timeout=float(os.getenv("OLLAMA_TIMEOUT", "180")),
        )
        raw = client.generate(prompt, require_json=True)
        ok, validated, error, raw_data = AIValidator.validate(raw, AnalysisResult)
        if not ok or validated is None:
            raise ValueError(f"AI output validation failed: {error}")

        result = validated.model_dump(by_alias=True)
        result["input_hash"] = __import__("hashlib").sha256(prompt.encode("utf-8")).hexdigest()
        result["output_hash"] = __import__("hashlib").sha256(raw.encode("utf-8")).hexdigest()
        return result
