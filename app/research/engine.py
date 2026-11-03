import uuid
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import List, Dict, Any, Optional

from app.research.models import ResearchTask, ResearchStatus, ClaimStatus
from app.research.research_result import ResearchResult, ResearchMetrics
from app.research.query_builder import QueryBuilder
from app.research.source_registry import SourceRegistry
from app.research.source_policy import SourcePolicy
from app.research.source_selector import SourceSelector
from app.research.search_adapter import SearchAdapter
from app.search.models import SearchResult
from app.research.document_processor import DocumentProcessor
from app.research.evidence_extractor import EvidenceExtractor
from app.research.team_mention import filter_by_team_mention
from app.research.claim_builder import ClaimBuilder
from app.research.claim_validator import ClaimValidator
from app.research.rivalry_guard import rivalry_rejection_reason
from app.research.conflict_detector import ConflictDetector
from app.database.research_repository import ResearchRepository


class _InjectedSearchAdapter:
    """Compatibility adapter for explicitly injected legacy search clients."""

    def __init__(self, client):
        self.client = client

    def search(self, query, **kwargs) -> List[SearchResult]:
        raw_results = self.client.search(query)
        if raw_results is None:
            return []
        if not isinstance(raw_results, list):
            raw_results = list(raw_results)

        normalized = []
        for item in raw_results:
            if isinstance(item, SearchResult):
                normalized.append(item)
                continue
            if not isinstance(item, dict):
                continue
            normalized.append(
                SearchResult(
                    title=str(item.get("title", "")),
                    url=str(item.get("url", "")),
                    content=str(item.get("content", item.get("text", ""))),
                    engine=item.get("engine"),
                    category=item.get("category"),
                    published_at=item.get("published_at"),
                    score=float(item.get("score", 0.0) or 0.0),
                    relevance=int(item.get("relevance", 0) or 0),
                    source_type=str(item.get("source_type", "search")),
                    retrieved_at=item.get("retrieved_at"),
                )
            )
        return normalized


class ResearchEngine:
    def __init__(
        self,
        search_client=None,
        crawler=None,
        repository: Optional[ResearchRepository] = None,
        search_adapter: Optional[SearchAdapter] = None,
    ):
        self.search_client = search_client
        self.crawler = crawler
        self.repository = repository or ResearchRepository()
        self.query_builder = QueryBuilder()
        self.source_registry = SourceRegistry()
        self.source_policy = SourcePolicy()
        self.source_selector = SourceSelector(self.source_registry)
        if search_adapter is not None:
            self.search_adapter = search_adapter
        elif search_client is not None:
            self.search_adapter = _InjectedSearchAdapter(search_client)
        else:
            self.search_adapter = SearchAdapter()
        self.document_processor = DocumentProcessor()
        self.evidence_extractor = EvidenceExtractor()
        self.claim_builder = ClaimBuilder()
        self.claim_validator = ClaimValidator()
        self.conflict_detector = ConflictDetector()

    def _crawl_parallel(self, urls: List[str]) -> List[Dict[str, Any]]:
        """Stáhne URL paralelně (`FAE_CRAWL_WORKERS`, výchozí 4), výsledky ve stejném pořadí.
        Chyba jedné URL nikdy nesmí shodit celý research – vrátí se `{"status": "error"}`."""
        def one(url: str) -> Dict[str, Any]:
            try:
                res = self.crawler.crawl(url)
                return res if isinstance(res, dict) else {"status": "error", "url": url, "error": "invalid crawler result"}
            except Exception as exc:
                return {"status": "error", "url": url, "error": str(exc)}

        try:
            workers = max(1, int(os.getenv("FAE_CRAWL_WORKERS", "4") or 4))
        except ValueError:
            workers = 4
        if workers == 1 or len(urls) <= 1:
            return [one(url) for url in urls]
        with ThreadPoolExecutor(max_workers=min(workers, len(urls))) as pool:
            return list(pool.map(one, urls))

    def _search_one(self, task: ResearchTask, q: Dict[str, Any]):
        """Jeden dotaz -> (výsledky, chyba, diagnostika). Diagnostika se čte hned ve stejném vlákně
        (`last_diagnostics` je vláknově lokální). Chyba se nevyhazuje, vrací se volajícímu."""
        team_name = self.subject_team_name(task)
        h2h_query = task.domain == "HEAD_TO_HEAD"
        try:
            res = self.search_adapter.search(
                q["query"],
                team="" if h2h_query else team_name,
                domain=task.domain,
                priority=task.priority,
                reason=q.get("type", ""),
                data_cutoff_at=task.data_cutoff_at,
                home_team=task.home_team if h2h_query else None,
                away_team=task.away_team if h2h_query else None,
                competition=task.competition if h2h_query else None,
            )
        except Exception as exc:
            return [], exc, None
        res = res if res is not None else []
        diag = getattr(res, "diagnostics", None) or getattr(self.search_adapter, "last_diagnostics", None)
        if not team_name and not h2h_query:
            # Zápasová doména bez týmového subjektu (GENERAL, EXPECTED_LINEUPS, RIVALRY, ...): SearchEngine zde identitu
            # neověřuje, proto se před stahováním vyžaduje zmínka domácího nebo hostujícího týmu (běh M976_e7ab).
            try:
                res = filter_by_team_mention(res, task.domain, task.home_team, task.away_team)
            except Exception:
                logging.getLogger(__name__).exception("Předfiltr zmínky týmu selhal (doména %s)", task.domain)
        return res, None, diag

    def _search_parallel(self, task: ResearchTask, planned: List[Dict[str, Any]]) -> List[tuple]:
        """Spustí dotazy souběžně (`FAE_SEARCH_WORKERS`, výchozí 3; 1 = sekvenčně). Výsledky jsou ve
        stejném pořadí jako dotazy; DB zápisy a vyhazování chyb dělá volající v jednom vlákně.
        Odstup startů požadavků na SearXNG nadále hlídají `SEARXNG_MIN_INTERVAL_SECONDS` a host-zámek."""
        try:
            workers = max(1, int(os.getenv("FAE_SEARCH_WORKERS", "3") or 3))
        except ValueError:
            workers = 3
        if workers == 1 or len(planned) <= 1:
            return [self._search_one(task, q) for q in planned]
        with ThreadPoolExecutor(max_workers=min(workers, len(planned))) as pool:
            return list(pool.map(lambda q: self._search_one(task, q), planned))

    @staticmethod
    def subject_team_name(task: ResearchTask) -> str:
        """Subjekt claimů podle domény (TODO 3.3): *_HOME -> domácí, *_AWAY -> hosté,
        ostatní (GENERAL, HEAD_TO_HEAD, REFEREE, RIVALRY, ...) = zápasová doména
        bez týmu (prázdný řetězec), nikdy ne „hosté jinak“."""
        domain = task.domain or ""
        if domain == "TEAM_PROFILE":
            return task.home_team
        if domain.endswith("_HOME"):
            return task.home_team
        if domain.endswith("_AWAY"):
            return task.away_team
        return ""

    def execute(self, task: ResearchTask) -> ResearchResult:
        start_time = time.time()
        exec_uuid = f"EXEC-{uuid.uuid4().hex[:8]}"
        session_uuid = f"RS-{uuid.uuid4().hex[:8]}"
        metrics = ResearchMetrics()

        self.repository.mark_task_running(task.task_id, task.attempt_number)
        exec_id = self.repository.create_execution(exec_uuid, task.task_id, task.attempt_number)

        try:
            session_id = self.repository.create_session(
                session_uuid, task.run_id, task.task_id, task.domain
            )
            queries = self.query_builder.build_queries(task)
            metrics.queries_count = len(queries)
            planned_queries = queries[: self.source_policy.get_strategy(task.domain).get("max_queries", len(queries))]
            search_results = []
            diag_warnings: List[str] = []

            first_search_error: Optional[Exception] = None
            failed_queries = 0

            for q, (res, search_err, diag) in zip(planned_queries, self._search_parallel(task, planned_queries)):
                if diag and hasattr(diag, "drop_reasons") and diag.drop_reasons:
                    diag_warnings.extend(diag.drop_reasons)

                try:
                    self.repository.save_query(session_id, q["query"], q["type"], q["hash"], len(res) if res else 0)
                except Exception as q_err:
                    pass

                if search_err is not None:
                    # Jeden vypršelý dotaz nesmí shodit celou doménu (běh M976: ReadTimeout → 8× FAILED).
                    failed_queries += 1
                    first_search_error = first_search_error or search_err
                    diag_warnings.append(f"Dotaz selhal ({type(search_err).__name__}): {q['query'][:80]}")
                    continue

                search_results.extend(res)

            if first_search_error is not None and not search_results:
                # všechny dotazy selhaly (SearXNG nedostupný) → skutečné FAILED se jménem výjimky
                raise first_search_error

            metrics.search_results_count = len(search_results)
            if not search_results:
                self.repository.complete_execution(exec_id, "NO_RESULT")
                metrics.duration_ms = int((time.time() - start_time) * 1000)
                final_warnings = diag_warnings if diag_warnings else [
                    f"Vyhledávání nevrátilo žádné použitelné výsledky pro doménu '{task.domain}' (raw_count=0 nebo vše vyřazeno filtrem)."
                ]
                return ResearchResult(
                    task_id=task.task_id,
                    execution_id=exec_uuid,
                    status=ResearchStatus.NO_RESULT,
                    warnings=final_warnings,
                    metrics=metrics,
                )

            selector_results = [
                {
                    "title": result.title,
                    "url": result.url,
                    "content": result.content,
                    "score": getattr(result, "relevance", result.score),
                    "relevance": getattr(result, "relevance", 0),
                    "source_type": result.source_type,
                    "published_at": result.published_at,
                }
                for result in search_results
            ]
            strategy = self.source_policy.get_strategy(task.domain)

            # Search may return the same URL multiple times across query variants.
            # Source policy counts unique source documents, so deduplicate by the
            # normalized selector URL before checking minimum source thresholds.
            unique_selector_results = {}
            for result in selector_results:
                url = self.source_selector.normalize_url(result.get("url", ""))
                if not url:
                    continue
                existing = unique_selector_results.get(url)
                if existing is None or result.get("relevance", 0) > existing.get("relevance", 0):
                    unique_selector_results[url] = result

            candidates = self.source_selector.select_candidates(list(unique_selector_results.values()))
            metrics.sources_selected = len(candidates)
            publisher_ids = {c.get("publisher_id") for c in candidates if c.get("publisher_id")}
            min_sources = int(strategy.get("min_sources", 1))
            min_independent = int(strategy.get("min_independent_sources", 1))
            if len(candidates) < min_sources or len(publisher_ids) < min_independent:
                self.repository.complete_execution(exec_id, "NO_RESULT")
                metrics.duration_ms = int((time.time() - start_time) * 1000)
                return ResearchResult(
                    task_id=task.task_id,
                    execution_id=exec_uuid,
                    status=ResearchStatus.NO_RESULT,
                    warnings=[
                        f"Source policy not satisfied: {len(candidates)}/{min_sources} sources, "
                        f"{len(publisher_ids)}/{min_independent} independent publishers"
                    ],
                    sources_count=len(candidates),
                    metrics=metrics,
                )
            crawled_docs = []
            for cand in candidates:
                self.repository.save_source_candidate(session_id, cand["url"], cand["domain"], cand["source_type"], cand["score"], True)
            # Stahování probíhá paralelně (sítť + Playwright jsou nejpomalejší část); DB zápisy,
            # zpracování dokumentů a metriky zůstávají v jednom vlákně a v původním pořadí kandidátů.
            crawl_results = self._crawl_parallel([cand["url"] for cand in candidates])
            for cand, crawl_res in zip(candidates, crawl_results):
                if crawl_res.get("status") == "success":
                    metrics.sources_crawled += 1
                    doc = self.document_processor.process(crawl_res)
                    if doc["quality"] == "VALID":
                        crawled_docs.append(doc)
                        metrics.documents_parsed += 1

            all_evidence = []
            subject_team = self.subject_team_name(task)
            entities = [subject_team] if subject_team else [task.home_team, task.away_team]
            for doc in crawled_docs:
                try:
                    extracted = self.evidence_extractor.extract_evidence(
                        doc, task.domain, entities=entities, competition=task.competition)
                except TypeError:  # vstřiknutý/legacy extraktor bez parametru `competition`
                    extracted = self.evidence_extractor.extract_evidence(doc, task.domain, entities=entities)
                all_evidence.extend(extracted)

            team_name = self.subject_team_name(task)
            claims = self.claim_builder.build_claims_from_evidence(all_evidence, team_name)
            metrics.claims_count = len(claims)
            claims = self.claim_validator.validate_claims(claims, task.data_cutoff_at)
            # TODO 12.3: tvrzení o derby/rivalitě musí v kontextu zmiňovat OBA soupeře z úkolu (jinak zamítnuto).
            for claim in claims:
                if claim.predicate == "rivalry_context" and claim.status == ClaimStatus.VALID:
                    reason = rivalry_rejection_reason(str(claim.object_value), task.home_team, task.away_team)
                    if reason:
                        claim.status = ClaimStatus.REJECTED
                        claim.reject_reason = reason
            if hasattr(self.claim_validator, "apply_source_weights"):
                claims = self.claim_validator.apply_source_weights(claims, self.source_registry)
            claims = self.conflict_detector.detect_and_resolve(claims)
            valid_claims = [c for c in claims if c.status == ClaimStatus.VALID]
            conflicted_claims = [c for c in claims if c.status == ClaimStatus.CONFLICTED]
            metrics.valid_claims_count = len(valid_claims)
            metrics.conflicts_count = len(conflicted_claims)

            claims_data = []
            for c in claims:
                claims_data.append({
                    "match_id": task.match_id,
                    "subject": c.subject,
                    "predicate": c.predicate,
                    "object": c.object_value,
                    "normalized_value": c.normalized_value,
                    "source_date": c.source_date.isoformat() if c.source_date else None,
                    "date_source": getattr(c, "date_source", None),
                    "confidence": c.confidence,
                    "status": c.status.value,
                    "evidence_list": [
                        {"document_id": ev.document_id, "source_url": ev.source_url, "text_fragment": ev.text_fragment, "published_at": ev.published_at.isoformat() if ev.published_at else None}
                        for ev in c.evidence_list
                    ],
                })
            self.repository.save_claims_and_evidence(task.run_id, task.task_id, claims_data)

            status = ResearchStatus.SUCCESS
            if conflicted_claims:
                status = ResearchStatus.CONFLICTED
            elif not valid_claims:
                status = ResearchStatus.NO_RESULT
            metrics.duration_ms = int((time.time() - start_time) * 1000)
            self.repository.complete_execution(exec_id, status.value)
            return ResearchResult(task_id=task.task_id, execution_id=exec_uuid, status=status, claims=claims, sources_count=metrics.sources_selected, documents_count=metrics.documents_parsed, evidence_count=len(all_evidence), conflicts_count=len(conflicted_claims), metrics=metrics)

        except Exception as e:
            # Běh M976: 8× FAILED s prázdnou chybou (výjimka s prázdným `str(e)`, nic v logu) → vždy typ výjimky + traceback.
            logging.getLogger(__name__).exception("Research %s (task %s) selhal", task.domain, task.task_id)
            detail = f"{type(e).__name__}: {e}".rstrip(": ")
            self.repository.complete_execution(exec_id, "FAILED", detail)
            metrics.duration_ms = int((time.time() - start_time) * 1000)
            return ResearchResult(task_id=task.task_id, execution_id=exec_uuid, status=ResearchStatus.FAILED, warnings=[detail], metrics=metrics)
