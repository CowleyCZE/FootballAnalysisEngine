import hashlib
import json
import os
from typing import Any, Dict

from app.ai.client import OllamaClient
from app.ai.context_builder import ContextBuilder
from app.ai.remote_client import DEFAULT_BASE_URL, DEFAULT_MODEL, RemoteLLMClient
from app.ai.schemas import AIOutput, AnalysisResult, DataQuality, KeyFactor
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
    def _conflict_text(conflict: Any) -> str:
        if isinstance(conflict, str):
            return conflict[:300]
        if isinstance(conflict, dict):
            parts = [f"{k}={v}" for k, v in conflict.items() if isinstance(v, (str, int, float)) and str(v).strip()]
            return "; ".join(parts)[:300]
        return str(conflict)[:300]

    @staticmethod
    def _compose_result(raw: str, match_id: int, context: Dict[str, Any]):
        """TODO 11.16: z malého výstupu AI (`AIOutput`: conclusion, key_factors, uncertainties) složí
        `AnalysisResult`. Vše ostatní je deterministické: `match_id`, `status`, `data_quality` a
        `conflicts_noted` z kontextu; `home/away_team_analysis` = None (AI je negeneruje).
        `evidence_ids` se ověřují proti kontextu: neexistující ID se zahodí (faktor bez platného
        důkazu také) a zapíše se do `uncertainties`. Nic se nedomýšlí.
        Vrací (AnalysisResult | None, chyba)."""
        ok, parsed, error, raw_data = AIValidator.validate(raw, AIOutput)
        if not ok or parsed is None:
            return None, error
        if isinstance(raw_data, dict) and str(raw_data.get("status", "")).strip().lower() == "insufficient_data":
            return None, "AI označila data za nedostatečná (insufficient_data)"
        conclusion = parsed.conclusion.strip()
        if not conclusion:
            return None, "AI nevrátila žádný závěr (conclusion)"

        try:
            data_quality = DataQuality.model_validate(context.get("data_quality") or {})
        except Exception as exc:
            return None, f"Neplatná data_quality z kontextu: {exc}"

        known_ids = set()
        for claim in context.get("claims") or []:
            for ev in claim.get("evidence") or []:
                ev_id = ev.get("evidence_id")
                if isinstance(ev_id, int):
                    known_ids.add(ev_id)

        uncertainties = [u for u in parsed.uncertainties if str(u).strip()]
        key_factors = []
        for factor in parsed.key_factors:
            valid = [i for i in factor.evidence_ids if i in known_ids]
            invalid = [i for i in factor.evidence_ids if i not in known_ids]
            if invalid:
                uncertainties.append(
                    f"Zahozena neexistující evidence_id {invalid} u faktoru „{factor.factor[:80]}“.")
            if not valid:
                uncertainties.append(f"Faktor „{factor.factor[:80]}“ vynechán: nemá platný odkaz na důkaz.")
                continue
            key_factors.append(KeyFactor(factor=factor.factor, importance=factor.importance, evidence_ids=valid))

        conflicts_noted = [t for t in (AIWorker._conflict_text(c) for c in context.get("conflicts") or []) if t]
        if not key_factors:
            # Fail-closed: závěr bez jediného faktoru s platným odkazem na důkaz není podložený (běh M594:
            # model napsal nepodložený závěr o „obhájci titulu“).
            return None, "AI nevrátila žádný klíčový faktor s platným odkazem na důkaz; závěr není podložený"
        return AnalysisResult(
            match_id=match_id,
            status="complete",
            data_quality=data_quality,
            home_team_analysis=None,
            away_team_analysis=None,
            key_factors=key_factors,
            uncertainties=uncertainties,
            conflicts_noted=conflicts_noted,
            conclusion=conclusion,
        ), "VALID"

    @staticmethod
    def execute(payload: Dict[str, Any]) -> Dict[str, Any]:
        if isinstance(payload, dict) and "payload_json" in payload and isinstance(payload.get("payload_json"), (str, dict)):
            inner = payload["payload_json"]
            if isinstance(inner, str):
                try:
                    inner = json.loads(inner)
                except Exception:
                    inner = {}
            if isinstance(inner, dict):
                merged = dict(payload)
                merged.update(inner)
                payload = merged

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
            "conflict with the tip, report it in uncertainties or conflicts_noted instead of altering the tip.\n"
            "Ignore claims that are not about the football clubs of this match (other sports, ancient "
            "history, other clubs with a similar name).\n"
            "OUTPUT: return one JSON object with exactly these keys: conclusion (non-empty string in "
            "Czech, 2-4 sentences), key_factors (list of objects {factor, importance 0-1, evidence_ids: "
            "list of integer evidence_id values from the context}), uncertainties (list of strings). "
            "Nothing else.\n\n"
            + json.dumps(context, ensure_ascii=False, separators=(",", ":"))
        )
        client = OllamaClient(
            base_url=os.getenv("OLLAMA_URL", "http://127.0.0.1:11434"),
            model=os.getenv("OLLAMA_MODEL", "qwen2.5:3b"),
            temperature=float(os.getenv("OLLAMA_TEMPERATURE", "0.1")),
            timeout=float(os.getenv("OLLAMA_TIMEOUT", "300")),
            max_retries=max(1, int(os.getenv("OLLAMA_MAX_RETRIES", "2"))),
        )
        client.json_schema = AIOutput.model_json_schema()

        # TODO 11.17: řetěz lokální Ollama -> volitelný vzdálený poskytovatel (jen záloha) -> insufficient_data.
        attempts = [("ollama", client)]
        remote_note = None
        if os.getenv("FAE_LLM_PROVIDER", "ollama").strip().lower() == "groq":
            api_key = os.getenv("GROQ_API_KEY", "").strip()
            if api_key:
                attempts.append(("groq", RemoteLLMClient(
                    api_key=api_key,
                    base_url=os.getenv("FAE_REMOTE_LLM_URL", DEFAULT_BASE_URL),
                    model=os.getenv("FAE_REMOTE_LLM_MODEL", DEFAULT_MODEL),
                    timeout=float(os.getenv("FAE_REMOTE_LLM_TIMEOUT", "60")),
                    max_retries=max(1, int(os.getenv("FAE_REMOTE_LLM_RETRIES", "2"))),
                )))
            else:
                remote_note = "Vzdálená AI záloha je zapnutá, ale chybí GROQ_API_KEY."

        validated = None
        raw = ""
        used_provider, used_model = "ollama", None
        errors = []
        for provider, llm in attempts:
            prefix = "" if provider == "ollama" else "Vzdálená AI záloha: "
            try:
                raw = llm.generate(prompt, require_json=True)
                validated, error = AIWorker._compose_result(raw, match_id, context)
                if validated is not None:
                    used_provider, used_model = provider, getattr(llm, "model", None)
                    break
                errors.append(f"{prefix}AI výstup nebyl validní: {error}")
            except (RuntimeError, ValueError) as exc:
                if provider == "ollama":
                    errors.append(f"Lokální AI služba neposkytla použitelný výstup: {exc}")
                else:
                    errors.append(f"{prefix}{exc}")
        if validated is None:
            if remote_note:
                errors.append(remote_note)
            return AIWorker._insufficient_data_result(match_id, " | ".join(errors), prompt)

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
        result["llm_provider"] = used_provider
        result["llm_model"] = used_model
        return result
