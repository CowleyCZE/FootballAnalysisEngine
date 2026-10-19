import json
import logging
import sqlite3
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


class ContextBuilder:
    def __init__(self, repository=None, db_path: str = "database/football.db"):
        self.repository = repository
        self.db_path = db_path

    def enrich_match_info(self, match_info: Dict[str, Any], match_id: Optional[int]) -> Dict[str, Any]:
        info = dict(match_info or {})
        if not match_id and ("match_id" in info or "id" in info):
            match_id = info.get("match_id") or info.get("id")

        if match_id and self.db_path:
            try:
                with sqlite3.connect(self.db_path) as conn:
                    conn.row_factory = sqlite3.Row
                    row = conn.execute("""
                        SELECT m.id as match_id, m.home_team_id, m.away_team_id, m.scheduled_at, m.venue,
                               th.name as home_team, ta.name as away_team, COALESCE(c.name, m.competition, '') as competition
                        FROM matches m
                        LEFT JOIN teams th ON m.home_team_id = th.id
                        LEFT JOIN teams ta ON m.away_team_id = ta.id
                        LEFT JOIN competitions c ON m.competition_id = c.id
                        WHERE m.id = ?
                    """, (match_id,)).fetchone()
                    if row:
                        if not info.get("home_team"):
                            info["home_team"] = row["home_team"] or f"Team_{row['home_team_id'] if 'home_team_id' in row.keys() else match_id}"
                        if not info.get("away_team"):
                            info["away_team"] = row["away_team"] or f"Team_{row['away_team_id'] if 'away_team_id' in row.keys() else match_id}"
                        if not info.get("competition"):
                            info["competition"] = row["competition"] or "Unknown Competition"
                        if not info.get("scheduled_at") and row["scheduled_at"]:
                            info["scheduled_at"] = row["scheduled_at"]
                        if not info.get("venue") and row["venue"]:
                            info["venue"] = row["venue"]

                    if not info.get("data_cutoff_at") and not info.get("cutoff_datetime") and not info.get("cutoff"):
                        r_row = None
                        if info.get("run_id"):
                            r_row = conn.execute("SELECT data_cutoff_at FROM pipeline_runs WHERE run_id = ?", (str(info["run_id"]),)).fetchone()
                        elif info.get("run_db_id"):
                            r_row = conn.execute("SELECT pr.data_cutoff_at FROM pipeline_runs pr JOIN runs r ON r.run_id = pr.run_id WHERE r.id = ?", (int(info["run_db_id"]),)).fetchone()
                        if r_row and r_row["data_cutoff_at"]:
                            info["data_cutoff_at"] = r_row["data_cutoff_at"]
            except Exception as err:
                logger.warning(f"Failed to enrich match_info from DB: {err}")

        cutoff_candidates = [
            info.get("data_cutoff_at"),
            info.get("cutoff_datetime"),
            info.get("cutoff")
        ]
        non_null_candidates = [c for c in cutoff_candidates if c is not None and str(c).strip() != ""]

        parsed_candidates = []
        has_invalid = False
        for cand in non_null_candidates:
            try:
                from app.orchestrator.match_resolver import parse_to_utc
                parsed_candidates.append(parse_to_utc(cand))
            except Exception:
                has_invalid = True

        has_conflict = False
        if len(parsed_candidates) > 1:
            first_c = parsed_candidates[0]
            if any(c != first_c for c in parsed_candidates[1:]):
                has_conflict = True

        if not non_null_candidates or has_invalid or has_conflict:
            info["data_cutoff_at"] = None
        else:
            info["data_cutoff_at"] = parsed_candidates[0].isoformat()

        info["match_id"] = match_id
        return info

    def load_claims_from_db(self, match_id: int, run_db_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """Load real claims and their supporting evidence from database."""
        claims_list = []
        if not match_id or not self.db_path:
            return claims_list

        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                query = "SELECT * FROM claims WHERE match_id = ? AND status IN ('VALID', 'VERIFIED')"
                params: List[Any] = [match_id]
                if run_db_id is not None:
                    query += " AND run_id = ?"
                    params.append(run_db_id)

                claim_rows = conn.execute(query, params).fetchall()

                for c_row in claim_rows:
                    claim_id = c_row["id"]
                    ev_rows = conn.execute("""
                        SELECT e.*, d.url as source_url, d.published_at
                        FROM claim_evidence ce
                        JOIN evidence e ON ce.evidence_id = e.id
                        JOIN documents d ON e.document_id = d.id
                        WHERE ce.claim_id = ?
                    """, (claim_id,)).fetchall()

                    evidence_list = []
                    for ev in ev_rows:
                        evidence_list.append({
                            "evidence_id": ev["id"],
                            "source_url": ev["source_url"],
                            "text_fragment": ev["quoted_text"] or ev["extracted_value"],
                            "published_at": ev["published_at"],
                            "confidence": ev["confidence"]
                        })

                    text = c_row["claim_text"] or ""
                    ctype = c_row["claim_type"] or ""
                    marker = f" {ctype} " if ctype else ""
                    if marker and marker in text:
                        subject, _, obj = text.partition(marker)
                        predicate = ctype
                    else:
                        parts = text.split(" ", 2)
                        subject = parts[0] if parts else ""
                        predicate = parts[1] if len(parts) > 1 else ctype
                        obj = parts[2] if len(parts) > 2 else ""
                    obj = obj or c_row["normalized_claim"] or ""

                    claims_list.append({
                        "claim_id": claim_id,
                        "subject": subject,
                        "predicate": predicate,
                        "object": obj,
                        "normalized_value": c_row["normalized_claim"],
                        "confidence": c_row["confidence"] or 0.5,
                        "status": c_row["status"] or "VALID",
                        "evidence": evidence_list
                    })
        except Exception as err:
            logger.warning(f"Failed to load claims from DB: {err}")

        return claims_list

    def load_statistics_from_db(self, match_id: int) -> Dict[str, Any]:
        """Load statistics from database if available."""
        if not match_id or not self.db_path:
            return {}

        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                row = conn.execute("SELECT * FROM match_statistics WHERE match_id = ?", (match_id,)).fetchone()
                if row:
                    return dict(row)
        except Exception as err:
            logger.warning(f"Failed to load statistics from DB: {err}")

        return {}

    @staticmethod
    def _resolve_run_ref(conn: sqlite3.Connection, match_info: Dict[str, Any],
                         run_db_id: Optional[int]) -> tuple:
        """Vrátí (runs.id, runs.run_id) pro daný běh, nebo (None, None).

        match_predictions.run_id je textové runs.run_id, statistical_snapshots.run_id
        je číselné runs.id, proto je potřeba znát obě hodnoty.
        """
        if run_db_id is None:
            run_db_id = match_info.get("run_db_id")
        row = None
        if run_db_id is not None:
            row = conn.execute("SELECT id, run_id FROM runs WHERE id = ?", (int(run_db_id),)).fetchone()
        elif match_info.get("run_id"):
            row = conn.execute("SELECT id, run_id FROM runs WHERE run_id = ?", (str(match_info["run_id"]),)).fetchone()
        return (int(row[0]), str(row[1])) if row else (None, None)

    def load_prediction_from_db(self, match_id: int, match_info: Optional[Dict[str, Any]] = None,
                                run_db_id: Optional[int] = None, same_run_only: bool = False) -> Dict[str, Any]:
        """Načte uloženou predikci skóre ze statistického modelu (match_predictions).

        Přednost má predikce stejného běhu; jinak nejnovější predikce zápasu
        s data_cutoff_at nepozdějším než cutoff kontextu. Nic se nedopočítává.
        """
        match_info = match_info or {}
        if not match_id or not self.db_path:
            return {}
        cutoff = match_info.get("data_cutoff_at")
        cutoff_sql = " AND julianday(data_cutoff_at) <= julianday(?)" if cutoff else ""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                _, run_text = self._resolve_run_ref(conn, match_info, run_db_id)
                row = None
                if run_text:
                    params: List[Any] = [match_id, run_text] + ([cutoff] if cutoff else [])
                    row = conn.execute(
                        "SELECT * FROM match_predictions WHERE match_id = ? AND run_id = ?" + cutoff_sql,
                        params,
                    ).fetchone()
                if row is None and not same_run_only:
                    params = [match_id] + ([cutoff] if cutoff else [])
                    row = conn.execute(
                        "SELECT * FROM match_predictions WHERE match_id = ?" + cutoff_sql +
                        " ORDER BY julianday(data_cutoff_at) DESC, id DESC LIMIT 1",
                        params,
                    ).fetchone()
                if row is None:
                    return {}

                factors = None
                if "factors_json" in row.keys() and row["factors_json"]:
                    try:
                        factors = json.loads(row["factors_json"])
                    except (ValueError, TypeError):
                        factors = None

                try:
                    scores = json.loads(row["score_probabilities_json"] or "{}")
                except (ValueError, TypeError):
                    scores = {}
                if not isinstance(scores, dict):
                    scores = {}
                top_scores = dict(sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:3])
                return {
                    "model_version": row["model_version"],
                    "run_id": row["run_id"],
                    "data_cutoff_at": row["data_cutoff_at"],
                    "sample_size": row["sample_size"],
                    "predicted_score": f"{row['predicted_home_goals']}-{row['predicted_away_goals']}",
                    "expected_goals": {
                        "home": row["expected_home_goals"],
                        "away": row["expected_away_goals"],
                    },
                    "probabilities_1x2": {
                        "home_win": row["home_win_probability"],
                        "draw": row["draw_probability"],
                        "away_win": row["away_win_probability"],
                    },
                    "top_scores": top_scores,
                    "prior_only": factors.get("prior_only") if isinstance(factors, dict) else None,
                }
        except Exception as err:
            logger.warning(f"Failed to load prediction from DB: {err}")
            return {}

    def load_snapshots_from_db(self, match_id: int, match_info: Optional[Dict[str, Any]] = None,
                               run_db_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """Načte statistické snapshoty (např. forma) zápasu ≤ cutoff, nejnovější na (tým, metriku)."""
        match_info = match_info or {}
        if not match_id or not self.db_path:
            return []
        cutoff = match_info.get("data_cutoff_at")
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                run_int, _ = self._resolve_run_ref(conn, match_info, run_db_id)
                match = conn.execute(
                    "SELECT home_team_id, away_team_id FROM matches WHERE id = ?", (match_id,)
                ).fetchone()
                if not match:
                    return []
                sql = ("SELECT team_id, metric, value, sample_size, coverage, data_cutoff_at, calculation_version "
                       "FROM statistical_snapshots WHERE match_id = ?")
                params: List[Any] = [match_id]
                if run_int is not None:
                    sql += " AND run_id = ?"
                    params.append(run_int)
                if cutoff:
                    sql += " AND julianday(data_cutoff_at) <= julianday(?)"
                    params.append(cutoff)
                sql += " ORDER BY id DESC"

                sides = {match["home_team_id"]: "home", match["away_team_id"]: "away"}
                seen = set()
                snapshots: List[Dict[str, Any]] = []
                for r in conn.execute(sql, params).fetchall():
                    key = (r["team_id"], r["metric"])
                    if key in seen:
                        continue
                    seen.add(key)
                    snapshots.append({
                        "team": sides.get(r["team_id"]),
                        "metric": r["metric"],
                        "value": r["value"],
                        "sample_size": r["sample_size"],
                        "coverage": r["coverage"],
                        "data_cutoff_at": r["data_cutoff_at"],
                        "calculation_version": r["calculation_version"],
                    })
                return snapshots
        except Exception as err:
            logger.warning(f"Failed to load statistical snapshots from DB: {err}")
            return []

    def load_statistical_output(self, match_id: int, match_info: Optional[Dict[str, Any]] = None,
                                run_db_id: Optional[int] = None) -> Dict[str, Any]:
        """Výstup statistického enginu pro AI: klíč `prediction` a `snapshots` (jen pokud existují)."""
        output: Dict[str, Any] = {}
        prediction = self.load_prediction_from_db(match_id, match_info, run_db_id)
        if prediction:
            output["prediction"] = prediction
        snapshots = self.load_snapshots_from_db(match_id, match_info, run_db_id)
        if snapshots:
            output["snapshots"] = snapshots
        return output

    @staticmethod
    def _calculate_freshness_score(claims: List[Dict[str, Any]]) -> float:
        dates = []
        now = datetime.now(timezone.utc)
        for claim in claims:
            for ev in claim.get("evidence", []):
                value = ev.get("published_at")
                if not value:
                    continue
                try:
                    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    if dt <= now:
                        dates.append(dt)
                except (TypeError, ValueError):
                    continue
        if not dates:
            return 0.0
        ages = [(now - dt).total_seconds() / 3600.0 for dt in dates]
        scores = [max(0.0, 1.0 - age / (30.0 * 24.0)) for age in ages]
        return round(sum(scores) / len(scores), 2)

    def build_context(
        self,
        match_info: Dict[str, Any],
        claims: Optional[List[Dict[str, Any]]] = None,
        statistics: Optional[Dict[str, Any]] = None,
        conflicts: Optional[List[Dict[str, Any]]] = None,
        max_claims: int = 30,
        max_evidence_per_claim: int = 3,
        max_excerpt_chars: int = 500,
        run_db_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        match_id = match_info.get("match_id") or match_info.get("id")
        if run_db_id is not None and "run_db_id" not in match_info:
            match_info = dict(match_info)
            match_info["run_db_id"] = run_db_id
        enriched_match_info = self.enrich_match_info(match_info, match_id)

        if claims is None and match_id and self.db_path:
            claims = self.load_claims_from_db(int(match_id), run_db_id)
        else:
            claims = list(claims) if claims is not None else []

        if statistics is None and match_id and self.db_path:
            statistics = self.load_statistics_from_db(int(match_id))
            # Predikce a snapshoty statistického modelu (jen čtení; nic se nedopočítává).
            statistics.update(self.load_statistical_output(int(match_id), enriched_match_info, run_db_id))
        else:
            statistics = dict(statistics) if statistics is not None else {}

        if conflicts is None:
            conflicts = []

        sorted_claims = sorted(
            claims, key=lambda c: c.get("confidence", 0.0), reverse=True
        )[:max_claims]

        formatted_claims = []
        source_urls = set()
        publisher_domains = set()
        official_domains = set()

        for c in sorted_claims:
            evidence_list = c.get("evidence", [])
            formatted_ev = []
            for ev in evidence_list[:max_evidence_per_claim]:
                url = ev.get("source_url") or ev.get("url")
                if url:
                    source_urls.add(url)
                    try:
                        domain = urlparse(url).netloc.lower().removeprefix("www.")
                    except Exception:
                        domain = ""
                    if domain:
                        publisher_domains.add(domain)
                    source_type = str(ev.get("source_type") or ev.get("source") or "").lower()
                    if source_type.startswith("official"):
                        official_domains.add(domain)

                formatted_ev.append({
                    "evidence_id": ev.get("id") or ev.get("evidence_id"),
                    "source": ev.get("source", "unknown"),
                    "url": url,
                    "published_at": ev.get("published_at"),
                    "excerpt": (ev.get("text_fragment") or ev.get("excerpt", ""))[:max_excerpt_chars]
                })

            formatted_claims.append({
                "claim_id": c.get("id") or c.get("claim_id"),
                "subject": c.get("subject"),
                "predicate": c.get("predicate"),
                "object": c.get("object") or c.get("normalized_value"),
                "confidence": c.get("confidence", 0.5),
                "status": c.get("status", "VALID"),
                "evidence": formatted_ev
            })

        missing_fields = []
        if not claims:
            missing_fields.append("claims")
        if not statistics:
            missing_fields.append("statistics")

        total_sources = len(source_urls)
        independent_sources = len(publisher_domains)
        conflicts_count = len(conflicts)

        score = 1.0
        if not claims:
            score -= 0.4
        if not statistics:
            score -= 0.3
        if conflicts_count > 0:
            score -= min(0.2, conflicts_count * 0.05)
        score = max(0.0, min(1.0, round(score, 2)))

        data_quality = {
            "score": score,
            "source_count": total_sources,
            "independent_sources": independent_sources,
            "official_sources": len({d for d in official_domains if d}),
            "conflicts": conflicts_count,
            "freshness_score": self._calculate_freshness_score(formatted_claims),
            "missing_data": missing_fields
        }

        return {
            "match": enriched_match_info,
            "statistics": statistics,
            "claims": formatted_claims,
            "team_profiles": self.load_team_profiles(enriched_match_info),
            "match_context": self.load_match_context(enriched_match_info),
            "conflicts": conflicts,
            "data_quality": data_quality
        }

    def load_team_profiles(self, match_info: Dict[str, Any]) -> Dict[str, Any]:
        """Load the newest stored team snapshots not newer than this run cutoff."""
        match_id = match_info.get("match_id")
        if not match_id or not self.db_path:
            return {}
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                match = conn.execute("SELECT home_team_id, away_team_id FROM matches WHERE id=?", (int(match_id),)).fetchone()
                if not match:
                    return {}
                cutoff = match_info.get("data_cutoff_at")
                profiles = {}
                for side, key in (("home", "home_team_id"), ("away", "away_team_id")):
                    team_id = match[key]
                    if team_id is None:
                        continue
                    if cutoff:
                        row = conn.execute("""SELECT profile_json, data_cutoff_at FROM team_profile_snapshots
                            WHERE team_id=? AND data_cutoff_at<=? ORDER BY data_cutoff_at DESC, id DESC LIMIT 1""", (team_id, cutoff)).fetchone()
                    else:
                        row = conn.execute("SELECT profile_json, data_cutoff_at FROM team_profile_snapshots WHERE team_id=? ORDER BY data_cutoff_at DESC, id DESC LIMIT 1", (team_id,)).fetchone()
                    if row:
                        profiles[side] = {"as_of": row["data_cutoff_at"], "profile": json.loads(row["profile_json"])}
                return profiles
        except (sqlite3.Error, ValueError, TypeError):
            logger.exception("Unable to load reusable team profiles")
            return {}

    def load_match_context(self, match_info: Dict[str, Any]) -> Dict[str, Any]:
        match_id = match_info.get("match_id")
        run_id = match_info.get("run_id")
        run_db_id = match_info.get("run_db_id")
        if not match_id or not self.db_path:
            return {}
        try:
            with sqlite3.connect(self.db_path) as conn:
                if not run_id and run_db_id is not None:
                    row = conn.execute("SELECT run_id FROM runs WHERE id=?", (int(run_db_id),)).fetchone()
                    run_id = row[0] if row else None
                if not run_id:
                    return {}
                row = conn.execute("SELECT context_json FROM match_context_snapshots WHERE match_id=? AND run_id=?", (int(match_id), str(run_id))).fetchone()
                return json.loads(row[0]) if row else {}
        except (sqlite3.Error, ValueError, TypeError):
            logger.exception("Unable to load match context snapshot")
            return {}
