import hashlib
import json
import os
import re
import unicodedata
from typing import Any, Dict, Optional

from app.ai.client import OllamaClient
from app.ai.context_builder import ContextBuilder
from app.ai.remote_client import DEFAULT_BASE_URL, DEFAULT_MODEL, RemoteLLMClient
from app.ai.schemas import AIOutput, AnalysisResult, DataQuality, KeyFactor
from app.ai.validator import AIValidator
from app.research.relevance_filter import sentence_is_relevant


_WEEKDAY_RE = (
    (0, re.compile(r"\b(pondel\w*|monday)\b")),
    (1, re.compile(r"\b(utery|uteri\w*|uterni\w*|tuesday)\b")),
    (2, re.compile(r"\b(streda|stredu|stredy|stredecn\w*|wednesday)\b")),
    (3, re.compile(r"\b(ctvrtek|ctvrtk\w*|ctvrtecn\w*|thursday)\b")),
    (4, re.compile(r"\b(patek|patk\w*|patecn\w*|friday)\b")),
    (5, re.compile(r"\b(sobot\w*|saturday)\b")),
    (6, re.compile(r"\b(nedel\w*|sunday)\b")),
)
# Obecné kmeny (první 4 písmena bez diakritiky), které samy o sobě nedokládají, že faktor vychází z důkazu.
_GENERIC_STEMS = frozenset({
    "zapa", "prot", "utka", "tymu", "tymy", "bude", "jsou", "jeho", "jeji", "muze", "maji", "kter",
    "bylo", "byla", "jako", "nebo", "tent", "tyto", "matc", "team", "will", "with", "that", "this", "from", "have",
})


# „Subjekt:predikát:hodnota“ – interní označení claimu opsané modelem.
_RAW_CLAIM_LABEL = re.compile(r"^[^:]{1,60}:[a-z][a-z_]{2,30}:")


def _fold_text(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    return "".join(c for c in text if not unicodedata.combining(c)).lower()


def _stems(value: Any) -> set:
    """Kmeny (první 4 písmena bez diakritiky; zvládne běžné skloňování) slov délky ≥ 4; čísla se berou celá."""
    folded = _fold_text(value)
    return {w[:4] for w in re.findall(r"[a-z]{4,}", folded)} | set(re.findall(r"\d+", folded))


_CAP_WORD = re.compile(r"[A-ZÁČĎÉĚÍŇÓŘŠŤÚŮÝŽ][a-záčďéěíňóřšťúůýž]{3,}")


def _unknown_names(text: str, known_folded: str) -> list:
    """Běh M976_a388: AI napsala „Lzejka Líška byl povolán…“ – jméno, které není nikde v kontextu. Velká slova uprostřed věty
    (nebo před dalším velkým slovem) musí mít v kontextu oporu (první 5 písmen bez diakritiky; zvládne skloky)."""
    unknown = []
    for sentence in re.split(r"(?<=[.!?])\s+", str(text or "")):
        words = sentence.split()
        for idx, word in enumerate(words):
            match = _CAP_WORD.match(word.strip("„“\"'(),;:"))
            if not match:
                continue
            if idx == 0:
                continue  # první slovo věty je velké vždy; jméno za ním („Lzejka Líška“) zachytí druhé slovo
            folded_word = _fold_text(match.group(0))
            stem = folded_word[:5]
            if stem in known_folded:
                continue
            # Běh M976_c93f: „Zlína/Zlínu“ (kmen „zlina“) neprošlo, protože v kontextu je „Zlín“ (4 písmena). Krátké
            # jméno (≤ 6 písmen) proto stačí doložit 4písmenným kmenem.
            if len(folded_word) <= 6 and len(folded_word) >= 4 and folded_word[:4] in known_folded:
                continue
            unknown.append(match.group(0))
    return unknown


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
    def _localize_ids(context: Dict[str, Any]):
        """Malý model (qwen2.5:3b, běh M944) místo DB ID (3530, 3531…) vrací pořadová čísla 1..10. Do promptu proto
        jde kopie kontextu s lokálními `evidence_id` 1..N (bez `claim_id`); skutečná ID se vracejí přes `id_map`.
        Vrací (kontext_pro_prompt, {lokální_id: skutečné_id})."""
        prompt_context = json.loads(json.dumps(context, ensure_ascii=False, default=str))
        id_map: Dict[int, int] = {}
        local_by_real: Dict[int, int] = {}
        for claim in prompt_context.get("claims") or []:
            claim.pop("claim_id", None)
            for ev in claim.get("evidence") or []:
                real = ev.get("evidence_id")
                if not isinstance(real, int):
                    continue
                if real not in local_by_real:
                    local_by_real[real] = len(local_by_real) + 1
                    id_map[local_by_real[real]] = real
                ev["evidence_id"] = local_by_real[real]
        return prompt_context, id_map

    @staticmethod
    def _match_weekday(context: Dict[str, Any]) -> Optional[int]:
        """Den v týdnu výkopu v pražském čase (0 = pondělí), nebo None, pokud není známý."""
        scheduled = (context.get("match") or {}).get("scheduled_at")
        if not scheduled:
            return None
        try:
            from zoneinfo import ZoneInfo
            from app.orchestrator.match_resolver import parse_to_utc
            return parse_to_utc(scheduled).astimezone(ZoneInfo("Europe/Prague")).weekday()
        except Exception:
            return None

    @staticmethod
    def _wrong_weekday(text: str, weekday: Optional[int]) -> Optional[int]:
        """Vrátí dne v týdnu uvedený v textu, který se liší od dne výkopu (jinak None). Nic se nedomýšlí."""
        if weekday is None:
            return None
        folded = _fold_text(text)
        for idx, pattern in _WEEKDAY_RE:
            if idx != weekday and pattern.search(folded):
                return idx
        return None

    @staticmethod
    def _factor_is_grounded(factor_text: str, evidence_texts: list, team_names: list) -> bool:
        """Běh M976: faktor „Slovácko má závazky na zápas“ odkazoval na důkaz, se kterým nesouvisel. Faktor musí sdílet
        aspoň jeden věcný kmen (ne název týmu ani obecné slovo) nebo číslo s textem citovaného důkazu/claimu.
        `FAE_AI_GROUNDING=0` kontrolu vypne (diagnostika)."""
        if os.getenv("FAE_AI_GROUNDING", "1").strip() == "0":
            return True
        team_stems = set()
        for name in team_names:
            team_stems |= _stems(name)
        factor_stems = _stems(factor_text) - team_stems - _GENERIC_STEMS
        if not factor_stems:
            return False
        evidence_stems = set()
        for text in evidence_texts:
            evidence_stems |= _stems(text)
        # Běh M976_1fad: faktor „…odehrála v návratovém zápasu v září“ prošel jediným sdíleným kmenem. Vyžadují se dva
        # (nebo všechny, má-li faktor méně věcných kmenů); `FAE_AI_GROUNDING_MIN_STEMS` hodnotu mění.
        try:
            needed = max(1, int(os.getenv("FAE_AI_GROUNDING_MIN_STEMS", "2")))
        except ValueError:
            needed = 2
        return len(factor_stems & evidence_stems) >= min(needed, len(factor_stems))

    @staticmethod
    def _tip_sentence(context: Dict[str, Any]) -> str:
        """Deterministická věta s tipem ze statistického modelu (běh M976_e7ab: závěr AI tip vůbec nezmiňoval a byl
        obecný). Čísla se jen přebírají z `statistics.prediction`; nic se nedopočítává ani nedomýšlí."""
        pred = (context.get("statistics") or {}).get("prediction")
        if not isinstance(pred, dict) or not pred.get("predicted_score") or pred.get("prior_only"):
            return ""
        match_ctx = context.get("match") or {}
        home, away = match_ctx.get("home_team") or "domácí", match_ctx.get("away_team") or "hosté"

        def _num(value: Any, digits: int = 2) -> Optional[str]:
            try:
                return f"{float(value):.{digits}f}".replace(".", ",")
            except (TypeError, ValueError):
                return None

        def _pct(value: Any) -> Optional[str]:
            try:
                number = float(value)
            except (TypeError, ValueError):
                return None
            return _num(number * 100 if number <= 1.0 else number, 1)

        text = f"Statistický model tipuje výsledek {str(pred['predicted_score']).replace('-', ':')}"
        xg = pred.get("expected_goals") or {}
        xg_h, xg_a = _num(xg.get("home")), _num(xg.get("away"))
        if xg_h and xg_a:
            text += f" (očekávané góly: {home} {xg_h}, {away} {xg_a}"
            probs = pred.get("probabilities_1x2") or {}
            p_h, p_d, p_a = _pct(probs.get("home_win")), _pct(probs.get("draw")), _pct(probs.get("away_win"))
            if p_h and p_d and p_a:
                text += f"; pravděpodobnosti výhra domácích / remíza / výhra hostů {p_h} % / {p_d} % / {p_a} %"
            text += ")"
        return text + "."

    @classmethod
    def _with_tip_sentence(cls, conclusion: str, context: Dict[str, Any]) -> str:
        tip = cls._tip_sentence(context)
        if not tip:
            return conclusion
        # Běh M976_1fad: závěr AI nic o statistikách neříkal. Za tip se přidají deterministické věty ze snapshotů (jsou-li).
        stat = " ".join(cls._statistical_factors(context)["sentences"])
        return f"{tip} {stat} {conclusion}".replace("  ", " ").strip()

    @staticmethod
    def _statistical_factors(context: Dict[str, Any]) -> Dict[str, Any]:
        """Běh M1_53d1: AI selhala (ořezaný JSON), a přestože měl statistický model tip i snapshoty, uživatel dostal jen
        `insufficient_data`. Tato funkce deterministicky převede uložené statistiky (forma, xGD, xG-Elo, top-3 skóre) na
        české věty. Berou se jen hodnoty ze snapshotů s `sample_size` > 0; nic se nedopočítává ani nedomýšlí.
        Vrací {"sentences": [...], "top_scores": str, "low_coverage": [...]}."""
        stats = context.get("statistics") or {}
        match_ctx = context.get("match") or {}
        names = {"home": match_ctx.get("home_team") or "domácí", "away": match_ctx.get("away_team") or "hosté"}
        by_metric: Dict[str, Dict[str, tuple]] = {}
        for snap in stats.get("snapshots") or []:
            if not isinstance(snap, dict):
                continue
            side, metric, value = snap.get("team"), snap.get("metric"), snap.get("value")
            if side not in names or value is None:
                continue
            try:
                sample = int(snap.get("sample_size") or 0)
                number = float(value)
            except (TypeError, ValueError):
                continue
            if sample <= 0:
                continue
            by_metric.setdefault(str(metric), {})[side] = (number, sample, snap.get("coverage"))

        def _fmt(value: float, digits: int = 2, signed: bool = False) -> str:
            text = f"{value:+.{digits}f}" if signed else f"{value:.{digits}f}"
            return text.replace(".", ",")

        def _pct(value: Any) -> Optional[str]:
            try:
                number = float(value)
            except (TypeError, ValueError):
                return None
            return _fmt(number * 100 if number <= 1.0 else number, 1)

        sentences = []
        form = by_metric.get("form_points") or {}
        if form:
            parts = [f"{names[s]} {_fmt(form[s][0], 0 if float(form[s][0]).is_integer() else 1)} b. z {form[s][1]} zápasů"
                     for s in ("home", "away") if s in form]
            sentences.append("Forma (body z posledních odehraných zápasů): " + ", ".join(parts) + ".")
        xgd = by_metric.get("xgd_ewma") or {}
        if xgd:
            parts = [f"{names[s]} {_fmt(xgd[s][0], 2, True)}" for s in ("home", "away") if s in xgd]
            sentences.append("Vážený průměrný rozdíl xG (vyšší hodnota = lepší bilance šancí): " + ", ".join(parts) + ".")
        elo = by_metric.get("xg_elo") or {}
        if elo:
            parts = [f"{names[s]} {_fmt(elo[s][0], 0)}" for s in ("home", "away") if s in elo]
            sentences.append("Výkonnostní rating xG-Elo: " + ", ".join(parts) + ".")

        low_coverage = []
        for metric in ("xgd_ewma", "xg_elo", "form_points"):
            for side, (_, _, coverage) in (by_metric.get(metric) or {}).items():
                try:
                    cov = float(coverage)
                except (TypeError, ValueError):
                    continue
                cov = cov * 100 if cov <= 1.0 else cov
                if cov < 60:
                    entry = f"{names[side]} ({_fmt(cov, 0)} %)"
                    if entry not in low_coverage:
                        low_coverage.append(entry)

        pred = stats.get("prediction") or {}
        top_parts = []
        for score, prob in (pred.get("top_scores") or {}).items():
            pct = _pct(prob)
            if pct:
                top_parts.append(f"{str(score).replace('-', ':')} ({pct} %)")
        return {"sentences": sentences, "top_scores": ", ".join(top_parts), "low_coverage": low_coverage}

    @classmethod
    def _deterministic_result(cls, match_id: int, context: Dict[str, Any], reasons: list, prompt: str = "") -> Optional[Dict[str, Any]]:
        """Záložní výstup bez LLM: závěr se skládá jen z tipu statistického modelu a uložených statistik (TODO 11.29).
        Vrací None, když není k dispozici použitelný tip (chybí, nebo je `prior_only`) – pak platí `insufficient_data`.
        `key_factors` zůstávají prázdné (nemají důkazy, audit by je označil jako `missing_evidence`); statistické
        podklady jsou v `statistical_factors`. Výsledek je označen `composition=deterministic_statistical`, takže audit
        i uživatel vidí, že AI vysvětlení chybí. `FAE_AI_DETERMINISTIC_FALLBACK=0` záložní cestu vypne."""
        if os.getenv("FAE_AI_DETERMINISTIC_FALLBACK", "1").strip() == "0":
            return None
        tip = cls._tip_sentence(context)
        if not tip:
            return None
        try:
            data_quality = DataQuality.model_validate(context.get("data_quality") or {})
        except Exception:
            return None
        facts = cls._statistical_factors(context)
        parts = [tip] + facts["sentences"]
        if facts["low_coverage"]:
            parts.append("Pokrytí xG daty je nižší u: " + ", ".join(facts["low_coverage"]) + ", proto jsou tyto hodnoty méně spolehlivé.")
        parts.append("Závěr je složen automaticky ze statistického modelu a uložených statistik; AI vysvětlení "
                     "ani informace z výzkumných zdrojů v něm nejsou zahrnuty.")
        statistical_factors = list(facts["sentences"])
        if facts["top_scores"]:
            statistical_factors.append("Nejpravděpodobnější výsledky podle modelu (top 3): " + facts["top_scores"] + ".")
        uncertainties = ["AI vysvětlení není k dispozici: " + (" | ".join(str(r) for r in reasons if r)[:600] or "důvod neuveden")]
        conflicts_noted = [t for t in (cls._conflict_text(c) for c in context.get("conflicts") or []) if t]
        result = AnalysisResult(
            match_id=match_id,
            status="complete",
            data_quality=data_quality,
            home_team_analysis=None,
            away_team_analysis=None,
            key_factors=[],
            uncertainties=uncertainties,
            conflicts_noted=conflicts_noted,
            conclusion=" ".join(parts),
        ).model_dump(by_alias=True)
        result["composition"] = "deterministic_statistical"
        result["statistical_factors"] = statistical_factors
        result["ai_failure_reasons"] = [str(r)[:600] for r in reasons if r]
        result["llm_provider"] = "deterministic"
        result["llm_model"] = None
        result["input_hash"] = hashlib.sha256(prompt.encode("utf-8")).hexdigest() if prompt else ""
        result["output_hash"] = hashlib.sha256(json.dumps(result, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")).hexdigest()
        return result

    @staticmethod
    def _compose_result(raw: str, match_id: int, context: Dict[str, Any], id_map: Optional[Dict[int, int]] = None):
        """TODO 11.16: z malého výstupu AI (`AIOutput`: conclusion, key_factors, uncertainties) složí
        `AnalysisResult`. Vše ostatní je deterministické: `match_id`, `status`, `data_quality` a
        `conflicts_noted` z kontextu; `home/away_team_analysis` = None (AI je negeneruje).
        `evidence_ids` se ověřují proti kontextu: neexistující ID se zahodí (faktor bez platného
        důkazu také) a zapíše se do `uncertainties`. Nic se nedomýšlí.
        Vrací (AnalysisResult | None, chyba)."""
        ok, parsed, error, raw_data = AIValidator.validate(raw, AIOutput)
        if not ok or parsed is None:
            if "JSON Decode Error" in str(error):
                snippet = re.sub(r"\s+", " ", str(raw or ""))[:160]
                return None, f"{error} (délka odpovědi {len(str(raw or ''))} znaků, začátek: {snippet!r})"
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
        claim_evidence: Dict[int, list] = {}
        evidence_text: Dict[int, str] = {}
        for claim in context.get("claims") or []:
            ids_for_claim = []
            claim_text = f"{claim.get('subject') or ''} {claim.get('predicate') or ''} {claim.get('object') or ''}"
            for ev in claim.get("evidence") or []:
                ev_id = ev.get("evidence_id")
                if isinstance(ev_id, int):
                    known_ids.add(ev_id)
                    ids_for_claim.append(ev_id)
                    evidence_text[ev_id] = f"{claim_text} {ev.get('excerpt') or ''}"
            if isinstance(claim.get("claim_id"), int) and ids_for_claim:
                claim_evidence[claim["claim_id"]] = ids_for_claim

        uncertainties = [u for u in parsed.uncertainties if str(u).strip()]
        match_ctx = context.get("match") or {}
        team_names = [match_ctx.get("home_team") or "", match_ctx.get("away_team") or ""]
        weekday = AIWorker._match_weekday(context)
        known_folded = _fold_text(json.dumps(
            {"m": match_ctx, "c": [{k: c.get(k) for k in ("subject", "predicate", "object")} | {
                "e": [ev.get("excerpt") for ev in c.get("evidence") or []]} for c in context.get("claims") or []],
             "s": context.get("statistics")}, ensure_ascii=False, default=str))
        # Běh M976: závěr říkal „v neděli“ u zápasu v sobotu. Věty s jiným dnem než den výkopu se odstraní.
        sentences = re.split(r"(?<=[.!?])\s+", conclusion)
        kept_sentences = []
        dropped_reasons = []
        for sentence in sentences:
            if AIWorker._wrong_weekday(sentence, weekday) is not None:
                dropped_reasons.append(f"den v týdnu mimo termín zápasu: „{sentence[:80]}“")
                continue
            unknown_in_sentence = _unknown_names(sentence, known_folded)
            if unknown_in_sentence:
                dropped_reasons.append(f"jméno bez opory {unknown_in_sentence[:3]}: „{sentence[:80]}“")
                continue
            kept_sentences.append(sentence)
        if len(kept_sentences) != len(sentences):
            uncertainties.append("Ze závěru byla odstraněna věta s dnem v týdnu neodpovídajícím termínu zápasu nebo se jménem bez opory v kontextu: "
                                 + "; ".join(dropped_reasons)[:400])
            conclusion = " ".join(kept_sentences).strip()
            if not conclusion:
                return None, ("Závěr AI obsahoval jen den v týdnu neodpovídající termínu zápasu nebo jméno bez opory v kontextu; "
                              "důvody vyřazení vět: " + "; ".join(dropped_reasons)[:500])
        dropped_from = len(uncertainties)  # důvody vyřazení faktorů se uvedou v chybě (běh M976_fe22: příčina nebyla vidět)
        key_factors = []
        for factor in parsed.key_factors:
            if AIWorker._wrong_weekday(factor.factor, weekday) is not None:
                uncertainties.append(f"Faktor „{factor.factor[:80]}“ vynechán: den v týdnu neodpovídá termínu zápasu.")
                continue
            label = _RAW_CLAIM_LABEL.match(factor.factor.strip())
            if label:
                # Běh M976_f6a9/1b8d: model opsal označení claimu „Slovácko:profile:Slovácko's home form…“. Označení se
                # odstraní a zůstane doslovný text claimu (nic se nevymýšlí; důkaz i věcná vazba se ověřují níže).
                cleaned = factor.factor.strip()[label.end():].strip()
                if len(cleaned) < 10:
                    uncertainties.append(f"Faktor „{factor.factor[:80]}“ vynechán: je to opsané označení claimu, ne vlastní formulace.")
                    continue
                if not sentence_is_relevant(cleaned):
                    # Běh M976_1b8d: pod označením byl tabulkový šum („…StatisticsPldWDLGFGAGDPPGLast 5Home Form603361“).
                    uncertainties.append(f"Faktor „{cleaned[:80]}“ vynechán: text claimu je tabulkový/UI šum.")
                    continue
                uncertainties.append(f"Faktor „{cleaned[:80]}“ převzat doslova z claimu (bez označení {label.group(0)}).")
                factor = factor.model_copy(update={"factor": cleaned})
            unknown = _unknown_names(factor.factor, known_folded)
            if unknown:
                uncertainties.append(f"Faktor „{factor.factor[:80]}“ vynechán: jméno {unknown[:3]} nemá oporu v kontextu.")
                continue
            if id_map:
                # lokální číslo z promptu -> skutečné evidence_id; neznámé číslo zůstává a propadne ověřením níže
                factor = factor.model_copy(update={"evidence_ids": [id_map.get(i, i) for i in factor.evidence_ids]})
            valid = [i for i in factor.evidence_ids if i in known_ids]
            invalid = [i for i in factor.evidence_ids if i not in known_ids]
            # Malý model (qwen2.5:3b, běh M943) často uvádí `claim_id` místo `evidence_id`. Neplatné ID, které je
            # známým `claim_id`, se převádí na skutečné evidence tohoto claimu (nic se nevymýšlí) a zapíše se to.
            remapped = []
            for bad in list(invalid):
                if bad in claim_evidence:
                    for ev_id in claim_evidence[bad]:
                        if ev_id not in valid:
                            valid.append(ev_id)
                    remapped.append(bad)
                    invalid.remove(bad)
            if remapped:
                uncertainties.append(
                    f"U faktoru „{factor.factor[:80]}“ bylo ID {remapped} pravděpodobně claim_id; přiřazeno k evidence těchto claimů.")
            if invalid:
                uncertainties.append(
                    f"Zahozena neexistující evidence_id {invalid} u faktoru „{factor.factor[:80]}“.")
            if not valid:
                uncertainties.append(f"Faktor „{factor.factor[:80]}“ vynechán: nemá platný odkaz na důkaz.")
                continue
            # Běh M976_1fad: jeden faktor odkazoval na 16 důkazů. Ponechají se jen ty, které faktor věcně podporují (max 5).
            supported = [i for i in valid if AIWorker._factor_is_grounded(factor.factor, [evidence_text.get(i, "")], team_names)]
            if not supported:
                uncertainties.append(f"Faktor „{factor.factor[:80]}“ vynechán: text citovaného důkazu s ním věcně nesouvisí.")
                continue
            if len(supported) < len(valid):
                uncertainties.append(f"U faktoru „{factor.factor[:80]}“ ponecháno {min(len(supported), 5)} z {len(valid)} odkazů na důkaz (ostatní věcně nesouvisejí).")
            key_factors.append(KeyFactor(factor=factor.factor, importance=factor.importance, evidence_ids=supported[:5]))

        conflicts_noted = [t for t in (AIWorker._conflict_text(c) for c in context.get("conflicts") or []) if t]
        if not key_factors:
            # Fail-closed: závěr bez jediného faktoru s platným odkazem na důkaz není podložený (běh M594:
            # model napsal nepodložený závěr o „obhájci titulu“).
            requested = sorted({i for f in parsed.key_factors for i in f.evidence_ids})[:10]
            return None, ("AI nevrátila žádný klíčový faktor s platným odkazem na důkaz; závěr není podložený "
                          f"(AI uvedla evidence_ids {requested}, v kontextu je {len(known_ids)} evidence_id "
                          f"u {len(context.get('claims') or [])} claimů, faktorů {len(parsed.key_factors)}); "
                          f"důvody vyřazení: {' '.join(uncertainties[dropped_from:])[:700] or 'žádné'}")
        return AnalysisResult(
            match_id=match_id,
            status="complete",
            data_quality=data_quality,
            home_team_analysis=None,
            away_team_analysis=None,
            key_factors=key_factors,
            uncertainties=uncertainties,
            conflicts_noted=conflicts_noted,
            conclusion=AIWorker._with_tip_sentence(conclusion, context),
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
            deterministic = AIWorker._deterministic_result(
                match_id, context, ["Chybí ověřená tvrzení (claims) z výzkumné pipeline pro tento zápas"])
            if deterministic is not None:
                return deterministic
            res = AIWorker._insufficient_data_result(
                match_id,
                "Chybí ověřená tvrzení (claims) z výzkumné pipeline pro tento zápas",
            )
            res["data_quality"]["missing_data"] = context.get("data_quality", {}).get("missing_data", ["claims"])
            return res

        cutoff = context.get("match", {}).get("data_cutoff_at") or "N/A"
        prompt_context, id_map = AIWorker._localize_ids(context)
        prompt = (
            f"STRICT DATA CUTOFF: {cutoff}\n"
            "Analyze the football match using ONLY the supplied context. "
            "Do not invent facts, statistics, players, injuries, sources or evidence. "
            "Every key factor must reference evidence_ids that exist in the context. "
            "evidence_ids are the 'evidence_id' numbers inside claims[].evidence[] (small integers 1, 2, 3, ...). "
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
            + json.dumps(prompt_context, ensure_ascii=False, separators=(",", ":"))
            + "\n\nPiš `conclusion` i `factor` česky (NOT in English). Nepřidávej žádná fakta mimo kontext, "
            "zejména ne den v týdnu ani termín zápasu – použij jen `match.scheduled_at`. Neuváděj příčiny, pozici v tabulce "
            "ani předpovědi výsledku, pokud nejsou v daném důkazu; `factor` formuluj vlastními slovy česky, "
            "nekopíruj text claimu ani jeho označení (např. „Tým:profile:…“)."
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
                validated, error = AIWorker._compose_result(raw, match_id, context, id_map)
                # Běh M976_5ca7: malý model vrátil faktory s `evidence_ids: []`. Jedna opravná iterace se zpětnou vazbou
                # (jen u zamítnutí kvůli chybějícímu/neplatnému podkladu; `FAE_AI_REPAIR_RETRIES=0` ji vypne).
                repairs = max(0, int(os.getenv("FAE_AI_REPAIR_RETRIES", "1") or 0))
                while validated is None and repairs > 0 and error and (
                        "klíčový faktor" in str(error) or "Závěr AI obsahoval" in str(error) or "JSON Decode Error" in str(error)):
                    repairs -= 1
                    json_hint = ""
                    if "JSON Decode Error" in str(error):
                        # Běh M1_53d1: výstup byl ořezaný uprostřed řetězce („Unterminated string“).
                        json_hint = ("\nPředchozí odpověď byla neúplný JSON (pravděpodobně ořezaná). Vrať KRATŠÍ a úplný JSON: "
                                     "`conclusion` nejvýše 2 věty, nejvýše 3 `key_factors`, bez zalomení řádků uvnitř textů.")
                    valid_ids = sorted(id_map) if id_map else sorted(
                        {ev.get("evidence_id") for c in context.get("claims") or [] for ev in c.get("evidence") or []
                         if isinstance(ev.get("evidence_id"), int)})
                    repair_prompt = (
                        prompt + "\n\nPŘEDCHOZÍ ODPOVĚĎ BYLA ZAMÍTNUTA: " + str(error)[:400]
                        + json_hint
                        + f"\nVrať znovu celý JSON. Každý faktor MUSÍ mít neprázdné `evidence_ids` s čísly z {valid_ids[:30]} "
                        "a musí věcně vycházet z textu právě těchto důkazů (citovat/parafrázovat jejich obsah). "
                        "Faktor, který žádný důkaz nepodporuje, vynech; raději vrať méně faktorů. "
                        "V závěru nepoužívej žádná jména osob ani dny v týdnu, které nejsou v kontextu; názvy klubů piš tak, jak jsou v kontextu."
                    )
                    raw = llm.generate(repair_prompt, require_json=True)
                    validated, error = AIWorker._compose_result(raw, match_id, context, id_map)
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
            # TODO 11.29: bez použitelného výstupu LLM se závěr složí deterministicky z tipu a statistik (je-li tip).
            deterministic = AIWorker._deterministic_result(match_id, context, errors, prompt)
            if deterministic is not None:
                return deterministic
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
