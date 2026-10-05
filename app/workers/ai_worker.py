import hashlib
import json
import os
from typing import Any, Dict

from app.ai.client import OllamaClient
from app.ai.context_builder import ContextBuilder
from app.ai.schemas import AnalysisResult
from app.ai.validator import AIValidator


class AIWorker:
    @staticmethod
    def _insufficient_data_result(match_id: int, reason: str, prompt: str = "") -> Dict[str, Any]:
        """Return an explicit safe fallback without fabricating football facts."""
        input_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest() if prompt else ""
        result = AnalysisResult(
            match_id=match_id,
            status="insufficient_data",
            data_quality={
                "score": 0.0,
                "source_count": 0,
                "independent_sources": 0,
                "official_sources": 0,
                "conflicts": 0,
                "freshness_score": 0.0,
                "missing_data": [reason],
            },
            home_team_analysis=None,
            away_team_analysis=None,
            key_factors=[],
            uncertainties=[reason],
            conflicts_noted=[],
            conclusion="AI analýzu nelze bezpečně dokončit, protože lokální AI služba není dostupná nebo její výstup nebyl validní. Nebyla doplněna žádná náhradní fotbalová data.",
        ).model_dump(by_alias=True)
        result["input_hash"] = input_hash
        result["output_hash"] = hashlib.sha256(json.dumps(result, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
        return result

    @staticmethod
    def execute(payload: Dict[str, Any]) -> Dict[str, Any]:
        match_id = int(payload.get("match_id"))
        run_db_id = payload.get("run_db_id")
        db_path = payload.get("db_path", "database/football.db")
        statistics = payload.get("statistics") or {}
        claims = payload.get("claims") or []
        conflicts = payload.get("conflicts") or []
        match_info = payload.get("match") or {"match_id": match_id}

        context_builder = ContextBuilder(db_path=db_path)
        context = context_builder.build_context(
            match_info=match_info,
            claims=claims,
            statistics=statistics,
            conflicts=conflicts,
            run_db_id=int(run_db_id) if run_db_id is not None else None,
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

        try:
            raw = client.generate(prompt, require_json=True)
            ok, validated, error, raw_data = AIValidator.validate(raw, AnalysisResult)
            if not ok or validated is None:
                return AIWorker._insufficient_data_result(
                    match_id,
                    f"AI výstup nebyl validní: {error}",
                    prompt,
                )
        except (RuntimeError, ValueError) as exc:
            # External AI availability or response validation must never cause
            # fabricated football data or a permanently stuck ANALYZING state.
            # The explicit insufficient-data result is audited as UNRESOLVED.
            return AIWorker._insufficient_data_result(
                match_id,
                f"Lokální AI služba neposkytla použitelný výstup: {exc}",
                prompt,
            )

        result = validated.model_dump(by_alias=True)
        result["input_hash"] = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        result["output_hash"] = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        return result
