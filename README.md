# Football Analysis Engine

Automated, evidence-first football match research and AI analysis system built on an orchestrator-worker architecture with SQLite.

## Architecture & Canonical Execution Flow

The system strictly follows an **evidence-first** paradigm with **mandatory data cutoff enforcement** (`data_cutoff_at`) and **zero-hallucination fallback**:

```
API Request (POST /api/analysis/start)
   │
   ▼
MatchResolver (Resolves MatchIdentity & cutoff)
   │
   ▼
MasterOrchestrator (Single canonical orchestrator)
   │
   ├─► ResearchPlanner (Generates domain-specific ResearchTasks)
   ├─► JobStore (SQLite job queue & state machine)
   │
   ├─► ResearchWorker (SearXNG -> Source Selection -> Crawl -> Parse)
   │      └─► EvidenceExtractor (Extracts domain evidence & metadata)
   │      └─► ClaimBuilder & ClaimValidator (Cutoff & source validation)
   │      └─► ConflictDetector (Resolves temporal/authority conflicts)
   │
   ├─► StatisticsWorker (Normalizes & validates match statistics)
   │
   ├─► AIWorker (DB-backed ContextBuilder -> Ollama AI Synthesis)
   │      └─► Returns insufficient_data if claims are absent
   │
   └─► AdversarialAuditor (Validates citations, cutoff & consistency)
          ├─► Passes: State -> FINALIZING -> COMPLETED
          └─► Fails: RepairQueue -> ResearchRequest -> Self-Correction Loop
```

## Key Architectural Principles

1. **Evidence-First & Zero-Hallucination**: AI operates purely as a synthesizer over database-verified claims. If no verified evidence is available, AI returns an explicit `insufficient_data` response instead of fabricating facts.
2. **Canonical Orchestration**: `MasterOrchestrator` is the single execution authority. `MatchOrchestrator` is a lightweight facade delegating directly to `MatchResolver` and `MasterOrchestrator`.
3. **Cutoff Enforcement**: All search queries, crawler documents, evidence items, claims, AI prompts, and audit checks strictly enforce `data_cutoff_at`. Information published after the cutoff is rejected.
4. **Resilient Recovery & Self-Correction**: Orphaned jobs with stale heartbeats are automatically recovered to `RETRY` status. Audit violations trigger repair research tasks up to `MAX_RETRIES`.

## API Endpoints

- `GET /health` or `GET /api/health`: Health status.
- `POST /api/analysis/start`: Start a new match analysis run (`match_id` or `home_team`, `away_team`, `competition`, `scheduled_at`).
- `GET /api/analysis/{run_id}`: Track execution state, current cycle, and job breakdown.
- `GET /api/analysis/{run_id}/result`: Retrieve final audited analysis result, key factors, claims, and audit report.
- `POST /api/workers/register`: Register worker instance capabilities.
- `POST /api/jobs/claim`: Atomically claim queued job.
- `POST /api/jobs/{job_id}/result`: Submit job completion or failure result.

## Running Tests

Execute unit, integration, recovery, and E2E tests:

```bash
python -m pytest
```
