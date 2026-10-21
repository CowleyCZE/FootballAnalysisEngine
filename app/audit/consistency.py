import re
from typing import Dict, Any, List, Optional, Tuple

# Skóre typu "2:1", "2-1", "2–1"; čas (20:00) se vylučuje v _extract_scores.
_SCORE_RE = re.compile(r"(?<![\d:.\-])(\d{1,2})\s*[:\-–]\s*(\d{1,2})(?![\d:])")
# Skóre se kontroluje jen ve větách, které mluví o tipu/predikci zápasu (ne o minulých výsledcích).
_TIP_CUES = ("tip", "predikc", "očekáv", "typuj", "skonč", "výsledek zápasu", "prediction", "predict", "expect")
# „vyhrál 7 z posledních 10“, „won 7 of the last 10“
_WIN_CLAIM_A = re.compile(r"(?:vyhr\w+|výhr\w*|won|wins?)\D{0,15}?(\d{1,2})\s*(?:z|of|out of)\s*(?:posledních|the last|last)?\s*(\d{1,2})")
# „7 výher z posledních 10“, „7 wins from last 10“
_WIN_CLAIM_B = re.compile(r"(\d{1,2})\s*(?:výher|výhr\w*|vyhr\w+|wins?)\s*(?:z|of|from|out of)\s*(?:posledních|the last|last)?\s*(\d{1,2})")


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
    def _team_records(stats: Dict[str, Any]) -> List[Dict[str, int]]:
        """Bilance týmů ze skutečné struktury statistik (`home_team.form` / `away_team.form` z FormEngine:
        `form_string` W-D-L, `points`, `sample_size`, `gf`, `ga`) + zpětně kompatibilní ploché
        klíče `wins/draws/losses/matches`."""
        records: List[Dict[str, int]] = []
        for side in ("home_team", "away_team"):
            form = (stats.get(side) or {}).get("form") if isinstance(stats.get(side), dict) else None
            if not isinstance(form, dict):
                continue
            letters = [p for p in str(form.get("form_string") or "").split("-") if p]
            records.append({
                "wins": letters.count("W"), "draws": letters.count("D"), "losses": letters.count("L"),
                "matches": int(form.get("sample_size") or 0), "letters": len(letters),
                "points": form.get("points"), "gf": form.get("gf"), "ga": form.get("ga"), "gd": form.get("gd"),
                "side": side,
            })
        if stats.get("wins") is not None:
            records.append({"wins": stats["wins"], "draws": stats.get("draws") or 0, "losses": stats.get("losses") or 0,
                            "matches": stats.get("matches"), "letters": None, "points": None, "side": "flat"})
        return records

    @staticmethod
    def _claimed_win_ratios(text: str) -> List[Tuple[int, int]]:
        """Tvrzení typu „vyhrál 7 z posledních 10“ / „7 výher z posledních 10“ / „won 7 of last 10“."""
        found = []
        for m in _WIN_CLAIM_A.finditer(text):
            found.append((int(m.group(1)), int(m.group(2))))
        for m in _WIN_CLAIM_B.finditer(text):
            found.append((int(m.group(1)), int(m.group(2))))
        return found

    @staticmethod
    def check_statistical_consistency(stats: Dict[str, Any], claims: List[Dict[str, Any]], analysis_dict: Dict[str, Any]) -> List[Dict[str, Any]]:
        issues = []
        records = ConsistencyChecker._team_records(stats)

        # 1. Vnitřní logika statistik (obecně pro každý tým)
        for rec in records:
            wins, draws, losses, total = rec["wins"], rec["draws"], rec["losses"], rec["matches"]
            if total is not None and wins + draws + losses != total:
                issues.append({
                    "type": "statistical_inconsistency",
                    "severity": "CRITICAL",
                    "description": f"Součet výher({wins}), remíz({draws}) a proher({losses}) neodpovídá celku({total})",
                    "requires_research": False
                })
            elif rec.get("points") is not None and rec["points"] != 3 * wins + draws:
                issues.append({
                    "type": "statistical_inconsistency",
                    "severity": "CRITICAL",
                    "description": f"Body ({rec['points']}) neodpovídají bilanci {wins}V-{draws}R-{losses}P",
                    "requires_research": False
                })
            if rec.get("gf") is not None and rec.get("ga") is not None and rec.get("gd") is not None \
                    and rec["gd"] != rec["gf"] - rec["ga"]:
                issues.append({
                    "type": "statistical_inconsistency",
                    "severity": "CRITICAL",
                    "description": f"Gólový rozdíl ({rec['gd']}) neodpovídá {rec['gf']}:{rec['ga']}",
                    "requires_research": False
                })

        # 2. Tvrzení AI o počtu výher oproti statistikám (jen pokud je ověřitelné: stejný počet zápasů)
        texts = [str(analysis_dict.get("conclusion") or "")]
        for factor in analysis_dict.get("key_factors") or []:
            if isinstance(factor, dict):
                texts.append(str(factor.get("factor") or ""))
        reported = set()
        for text in texts:
            for claimed_wins, claimed_n in ConsistencyChecker._claimed_win_ratios(text.lower()):
                comparable = [r for r in records if r["matches"] in (claimed_n, None)]
                if not comparable or any(r["wins"] == claimed_wins for r in comparable) or (claimed_wins, claimed_n) in reported:
                    continue
                reported.add((claimed_wins, claimed_n))
                actual = "/".join(str(r["wins"]) for r in comparable)
                issues.append({
                    "type": "statistical_contradiction",
                    "severity": "CRITICAL",
                    "description": f"AI uvádí {claimed_wins} výher z {claimed_n}, ale statistická vrstva obsahuje {actual} výher",
                    "requires_research": False
                })

        # 3. Kontrola, že AI text neodporuje tipu statistického modelu
        prediction = stats.get("prediction")
        if isinstance(prediction, dict):
            issues.extend(ConsistencyChecker.check_prediction_consistency(prediction, analysis_dict))

        return issues
