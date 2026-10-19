import re
from typing import Dict, Any, List, Optional, Tuple

# Skóre typu "2:1", "2-1", "2–1"; čas (20:00) se vylučuje v _extract_scores.
_SCORE_RE = re.compile(r"(?<![\d:.\-])(\d{1,2})\s*[:\-–]\s*(\d{1,2})(?![\d:])")
# Skóre se kontroluje jen ve větách, které mluví o tipu/predikci zápasu (ne o minulých výsledcích).
_TIP_CUES = ("tip", "predikc", "očekáv", "typuj", "skonč", "výsledek zápasu", "prediction", "predict", "expect")


class ConsistencyChecker:
    @staticmethod
    def _predicted_score(prediction: Dict[str, Any]) -> Optional[Tuple[int, int]]:
        """Tip skóre z predikce ("predicted_score": "2-1" nebo predicted_home/away_goals)."""
        text = prediction.get("predicted_score")
        if text:
            m = _SCORE_RE.search(str(text))
            if m:
                return int(m.group(1)), int(m.group(2))
        try:
            return int(prediction["predicted_home_goals"]), int(prediction["predicted_away_goals"])
        except (KeyError, TypeError, ValueError):
            return None

    @staticmethod
    def _extract_scores(sentence: str) -> List[Tuple[int, int]]:
        scores = []
        for m in _SCORE_RE.finditer(sentence):
            first, second = m.group(1), m.group(2)
            # "20:00" / "18:30" jsou časy, ne skóre.
            if len(second) == 2 and second.startswith("0"):
                continue
            if int(first) > 15 or int(second) > 15:
                continue
            scores.append((int(first), int(second)))
        return scores

    @staticmethod
    def check_prediction_consistency(prediction: Dict[str, Any], analysis_dict: Dict[str, Any]) -> List[Dict[str, Any]]:
        """AI text nesmí odporovat tipu statistického modelu. Nesoulad je jen WARNING."""
        if not isinstance(prediction, dict) or not prediction:
            return []
        predicted = ConsistencyChecker._predicted_score(prediction)
        if predicted is None:
            return []

        texts = [str(analysis_dict.get("conclusion") or "")]
        for factor in analysis_dict.get("key_factors") or []:
            if isinstance(factor, dict):
                texts.append(str(factor.get("factor") or ""))

        issues: List[Dict[str, Any]] = []
        reported = set()
        for text in texts:
            for sentence in re.split(r"(?<=[.!?])\s+|\n", text):
                lowered = sentence.lower()
                if not any(cue in lowered for cue in _TIP_CUES):
                    continue
                scores = ConsistencyChecker._extract_scores(sentence)
                if not scores or predicted in scores or sentence in reported:
                    continue
                reported.add(sentence)
                issues.append({
                    "type": "prediction_contradiction",
                    "severity": "WARNING",
                    "description": (
                        f"AI text uvádí skóre {scores[0][0]}:{scores[0][1]}, ale tip statistického modelu je "
                        f"{predicted[0]}:{predicted[1]}. AI nemá tip měnit, jen vysvětlovat."
                    ),
                    "requires_research": False,
                })
        return issues

    @staticmethod
    def check_statistical_consistency(stats: Dict[str, Any], claims: List[Dict[str, Any]], analysis_dict: Dict[str, Any]) -> List[Dict[str, Any]]:
        issues = []
        
        # 1. Kontrola logického součtu statistik
        wins = stats.get("wins")
        draws = stats.get("draws")
        losses = stats.get("losses")
        total_matches = stats.get("matches")

        if wins is not None and draws is not None and losses is not None and total_matches is not None:
            if wins + draws + losses != total_matches:
                issues.append({
                    "type": "statistical_inconsistency",
                    "severity": "CRITICAL",
                    "description": f"Součet výher({wins}), remíz({draws}) a proher({losses}) neodpovídá celku({total_matches})",
                    "requires_research": False
                })

        # 2. Kontrola tvrzení AI oproti oficiálním statistikám
        conclusion = analysis_dict.get("conclusion", "").lower()
        if "vyhrál 7 z posledních 10" in conclusion and wins is not None and wins != 7:
            issues.append({
                "type": "statistical_contradiction",
                "severity": "CRITICAL",
                "description": f"AI uvádí 7 výher, ale statistická vrstva obsahuje {wins} výher",
                "requires_research": False
            })

        # 3. Kontrola, že AI text neodporuje tipu statistického modelu
        prediction = stats.get("prediction")
        if isinstance(prediction, dict):
            issues.extend(ConsistencyChecker.check_prediction_consistency(prediction, analysis_dict))

        return issues
