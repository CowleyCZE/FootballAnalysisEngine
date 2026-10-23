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
            conclusion="AI analýzu nelze bezpečně dokončit z důvodu nedostatku ověřených dat nebo nedostupnosti AI služby. Nebyla doplněna žádná náhradní fotbalová data.",
        ).model_dump(by_alias=True)
        result["input_hash"] = input_hash
        result["output_hash"] = hashlib.sha256(json.dumps(result, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
        return result

    @staticmethod
    def execute(payload: Dict[str, Any]) -> Dict[str, Any]:
        match_id = int(payload.get("match_id") or 0)
        run_db_id = payload.get("run_db_id")
        db_path = payload.get("db_path", "database/football.db")
        # None (not []) lets ContextBuilder load verified data from the DB.
        statistics = payload.get("statistics") or None
        claims = payload.get("claims") or None
        conflicts = payload.get("conflicts") or []
        match_info = dict(payload.get("match") or {"match_id": match_id})

        candidates = []
        for k in ("data_cutoff_at", "cutoff_datetime", "cutoff"):
            if payload.get(k) is not None and str(payload.get(k)).strip() != "":
                candidates.append(payload.get(k))
            if match_info.get(k) is not None and str(match_info.get(k)).strip() != "":
                candidates.append(match_info.get(k))

        parsed_cutoffs = []
        has_invalid_cutoff = False
        for c in candidates:
            try:
                from app.orchestrator.match_resolver import parse_to_utc
                parsed_cutoffs.append(parse_to_utc(c))
            except Exception:
                has_invalid_cutoff = True

        has_conflicting_cutoff = False
        if len(parsed_cutoffs) > 1:
            first_c = parsed_cutoffs[0]
            if any(c != first_c for c in parsed_cutoffs[1:]):
                has_conflicting_cutoff = True

        if not candidates or has_invalid_cutoff or has_conflicting_cutoff:
            reason = "Data cutoff time (data_cutoff_at) is missing or invalid"
            if has_conflicting_cutoff:
                reason = "Inconsistent cutoff values in payload"
            res = AIWorker._insufficient_data_result(match_id, reason)
            missing = ["claims", "statistics", "data_cutoff_at"] if not claims else ["data_cutoff_at"]
            res["data_quality"]["missing_data"] = missing
            return res

        valid_cutoff_str = parsed_cutoffs[0].isoformat()
        for k in ("data_cutoff_at", "cutoff_datetime", "cutoff"):
            match_info[k] = valid_cutoff_str

        context_builder = ContextBuilder(db_path=db_path)
        context = context_builder.build_context(
            match_info=match_info,
            claims=claims,
            statistics=statistics,
            conflicts=conflicts,
            run_db_id=int(run_db_id) if run_db_id is not None else None,
            max_claims=max(5, int(os.getenv("FAE_AI_MAX_CLAIMS", "16"))),
            max_evidence_per_claim=max(1, int(os.getenv("FAE_AI_MAX_EVIDENCE_PER_CLAIM", "2"))),
            max_excerpt_chars=max(160, int(os.getenv("FAE_AI_MAX_EXCERPT_CHARS", "320"))),
        )

        # Zero-hallucination check: if no claims available, return insufficient_data immediately
        if not context.get("claims"):
            res = AIWorker._insufficient_data_result(
                match_id,
                "Chybí ověřená tvrzení (claims) z výzkumné pipeline pro tento zápas",
            )
            res["data_quality"]["missing_data"] = context.get("data_quality", {}).get("missing_data", ["claims"])
            return res

        cutoff = context.get("match", {}).get("data_cutoff_at") or "N/A"
        prompt = (
            f"STRICT DATA CUTOFF: {cutoff}\n"
            "Analyze the football match using ONLY the supplied context. "
            "Do not invent facts, statistics, players, injuries, sources or evidence. "
            "Every key factor must reference evidence_ids that exist in the context. "
            "If data is insufficient, explicitly return status='insufficient_data'.\n"
            # Tip skóre počítá deterministický statistický model; AI ho jen vysvětluje.
            "If the context contains statistics.prediction, it is the authoritative output of the "
            "deterministic statistical model (predicted score, expected goals, 1-X-2 probabilities). "
            "You MUST NOT change, replace, recompute or contradict this tip. Only explain which evidence "
            "in the context supports or weakens it and state the uncertainty. If a claim seems to "
            "conflict with the tip, report it in uncertainties or conflicts_noted instead of altering the tip.\n\n"
            + json.dumps(context, ensure_ascii=False, separators=(",", ":"))
        )
        client = OllamaClient(
            base_url=os.getenv("OLLAMA_URL", "http://127.0.0.1:11434"),
            model=os.getenv("OLLAMA_MODEL", "qwen2.5:3b"),
            temperature=float(os.getenv("OLLAMA_TEMPERATURE", "0.1")),
            timeout=float(os.getenv("OLLAMA_TIMEOUT", "300")),
            max_retries=max(1, int(os.getenv("OLLAMA_MAX_RETRIES", "2"))),
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
            return AIWorker._insufficient_data_result(
                match_id,
                f"Lokální AI služba neposkytla použitelný výstup: {exc}",
                prompt,
            )

        # Check if cutoff was missing or invalid: AIWorker cannot produce usable result without valid cutoff
        cutoff_valid = False
        if cutoff and cutoff != "N/A":
            try:
                from app.orchestrator.match_resolver import parse_to_utc
                parse_to_utc(cutoff)
                cutoff_valid = True
            except Exception:
                cutoff_valid = False

        if not cutoff_valid:
            return AIWorker._insufficient_data_result(
                match_id,
                "Data cutoff time (data_cutoff_at) is missing or invalid",
                prompt,
            )

        result = validated.model_dump(by_alias=True)
        result["input_hash"] = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        result["output_hash"] = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        return result
