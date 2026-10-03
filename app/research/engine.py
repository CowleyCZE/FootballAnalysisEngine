import uuid
import time
from datetime import datetime
from typing import List, Dict, Any, Optional

from app.research.models import ResearchTask, ResearchStatus, ClaimStatus
from app.research.research_result import ResearchResult, ResearchMetrics
from app.research.query_builder import QueryBuilder
from app.research.source_registry import SourceRegistry
from app.research.source_policy import SourcePolicy
from app.research.source_selector import SourceSelector
from app.research.document_processor import DocumentProcessor
from app.research.evidence_extractor import EvidenceExtractor
from app.research.claim_builder import ClaimBuilder
from app.research.claim_validator import ClaimValidator
from app.research.conflict_detector import ConflictDetector
from app.database.research_repository import ResearchRepository

class ResearchEngine:
    def __init__(self, search_client, crawler, repository: Optional[ResearchRepository] = None):
        self.search_client = search_client
        self.crawler = crawler
        self.repository = repository or ResearchRepository()
        
        self.query_builder = QueryBuilder()
        self.source_registry = SourceRegistry()
        self.source_policy = SourcePolicy()
        self.source_selector = SourceSelector(self.source_registry)
        self.document_processor = DocumentProcessor()
        self.evidence_extractor = EvidenceExtractor()
        self.claim_builder = ClaimBuilder()
        self.claim_validator = ClaimValidator()
        self.conflict_detector = ConflictDetector()

    def execute(self, task: ResearchTask) -> ResearchResult:
        start_time = time.time()
        exec_uuid = f"EXEC-{uuid.uuid4().hex[:8]}"
        session_uuid = f"RS-{uuid.uuid4().hex[:8]}"
        
        metrics = ResearchMetrics()
        exec_id = self.repository.create_execution(exec_uuid, task.task_id, task.attempt_number)
        session_id = self.repository.create_session(session_uuid, task.run_id, task.task_id, task.domain)

        try:
            # 1. Query Builder
            queries = self.query_builder.build_queries(task)
            metrics.queries_count = len(queries)

            search_results = []
            for q in queries:
                res = self.search_client.search(q["query"])
                search_results.extend(res)
                self.repository.save_query(session_id, q["query"], q["type"], q["hash"], len(res))

            metrics.search_results_count = len(search_results)

            if not search_results:
                self.repository.complete_execution(exec_id, "NO_RESULT")
                return ResearchResult(
                    task_id=task.task_id,
                    execution_id=exec_uuid,
                    status=ResearchStatus.NO_RESULT,
                    metrics=metrics
                )

            # 2. Source Selection
            candidates = self.source_selector.select_candidates(search_results)
            metrics.sources_selected = len(candidates)

            crawled_docs = []
            for cand in candidates:
                self.repository.save_source_candidate(
                    session_id, cand["url"], cand["domain"], cand["source_type"], cand["score"], True
                )
                
                # 3. Crawler
                crawl_res = self.crawler.crawl(cand["url"])
                if crawl_res.get("status") == "success":
                    metrics.sources_crawled += 1
                    
                    # 4. Document Processor
                    doc = self.document_processor.process(crawl_res)
                    if doc["quality"] == "VALID":
                        crawled_docs.append(doc)
                        metrics.documents_parsed += 1

            # 5. Evidence & Claims
            all_evidence = []
            for doc in crawled_docs:
                evs = self.evidence_extractor.extract_evidence(doc, task.domain)
                all_evidence.extend(evs)

            team_name = task.home_team if "HOME" in task.domain else task.away_team
            claims = self.claim_builder.build_claims_from_evidence(all_evidence, team_name)
            metrics.claims_count = len(claims)

            # 6. Validation & Conflict Detection
            claims = self.claim_validator.validate_claims(claims, task.data_cutoff_at)
            claims = self.conflict_detector.detect_and_resolve(claims)

            valid_claims = [c for c in claims if c.status == ClaimStatus.VALID]
            conflicted_claims = [c for c in claims if c.status == ClaimStatus.CONFLICTED]

            metrics.valid_claims_count = len(valid_claims)
            metrics.conflicts_count = len(conflicted_claims)

            # 7. Uložení výsledků
            claims_data = []
            for c in claims:
                claims_data.append({
                    "match_id": task.match_id,
                    "subject": c.subject,
                    "predicate": c.predicate,
                    "object": c.object_value,
                    "normalized_value": c.normalized_value,
                    "source_date": c.source_date.isoformat() if c.source_date else None,
                    "confidence": c.confidence,
                    "status": c.status.value,
                    "evidence_list": [
                        {
                            "document_id": ev.document_id,
                            "source_url": ev.source_url,
                            "text_fragment": ev.text_fragment,
                            "published_at": ev.published_at.isoformat() if ev.published_at else None
                        } for ev in c.evidence_list
                    ]
                })
            
            self.repository.save_claims_and_evidence(task.run_id, task.task_id, claims_data)

            # 8. Určení výsledného stavu
            status = ResearchStatus.SUCCESS
            if conflicted_claims:
                status = ResearchStatus.CONFLICTED
            elif not valid_claims:
                status = ResearchStatus.NO_RESULT

            metrics.duration_ms = int((time.time() - start_time) * 1000)
            self.repository.complete_execution(exec_id, status.value)

            return ResearchResult(
                task_id=task.task_id,
                execution_id=exec_uuid,
                status=status,
                claims=claims,
                sources_count=metrics.sources_selected,
                documents_count=metrics.documents_parsed,
                evidence_count=len(all_evidence),
                conflicts_count=len(conflicted_claims),
                metrics=metrics
            )

        except Exception as e:
            self.repository.complete_execution(exec_id, "FAILED", str(e))
            metrics.duration_ms = int((time.time() - start_time) * 1000)
            return ResearchResult(
                task_id=task.task_id,
                execution_id=exec_uuid,
                status=ResearchStatus.FAILED,
                warnings=[str(e)],
                metrics=metrics
            )
