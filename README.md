# Football Analysis Engine

Automated, evidence-first football match research and AI analysis system built on an orchestrator-worker architecture with SQLite.

## Architecture & Canonical Execution Flow

The system strictly follows an **evidence-first** paradigm with **mandatory data cutoff enforcement** (`data_cutoff_at`) and **zero-hallucination fallback**:

```
API Request (POST /api/analysis/start)
   │
   ▼
MasterOrchestrator (Single canonical orchestrator; zápas zadaný uživatelem je
   │                  důvěryhodný => auto-RESOLVED, MatchResolver v toku není)
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
2. **Canonical Orchestration**: `MasterOrchestrator` is the single execution authority. `MatchOrchestrator` is a lightweight facade delegating directly to `MasterOrchestrator` (no `MatchResolver` in the production flow; a user-entered match is trusted and marked `RESOLVED`).
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

## Running Workers

To start a worker processing all background job capabilities (RESEARCH, SEARCH, CRAWL, STATISTICS, AI_ANALYSIS, AUDIT), run from the repository root:

```bash
python3 scripts/run_worker.py --worker-id worker-1
```

## Running Tests

Execute unit, integration, recovery, and E2E tests:

```bash
python -m pytest
```

Aktuální stav (21. 10. 2026): **315 passed** (~10–25 s).

## Exact-score prediction

The statistical phase now produces an explainable exact-score distribution with
model version `poisson-dc-context-v5`. It combines:

- recent form and goals/xG with exponential recency weighting,
- a venue split that shrinks toward all matches when the split sample is small,
- low-weight, recency-aware head-to-head history,
- bounded context adjustments for fatigue, absences/multipliers, rivalry,
  weather and style matchup,
- normalized probabilities for the complete 0–7 goal grid and the most likely score.

Every prediction contains `factors`, `sample_size`, the expected goals and the
three 1X2 probabilities so the result can be reviewed rather than treated as a
black box. Missing optional context is ignored; it is never invented.

**Rule for missing history (one rule):** if either team has no historical
matches (zero sample, or history for one team only => `prior_only`), the
statistics result has status `INSUFFICIENT_DATA` and the pipeline ends
`UNRESOLVED`; the neutral league prior is only shown as a low-confidence
prediction, never treated as a usable result. The legacy status
`COMPLETED_WITH_PRIOR` is not produced and not accepted.

The autonomous research plan also collects recent form and last matches,
home/away performance, goals, xG and xGA, fixture congestion and travel,
motivation, expected lineups, referee profile, rivalry, weather and tactical
style matchup. Recent observations use recency weighting, venue splits shrink
when the sample is small, and H2H is capped at a maximum 15% influence. Valid
research snapshots are converted into bounded fatigue, motivation, rivalry,
weather and style corrections; explicit numeric context supplied by a caller
overrides these derived corrections.

### CLI – direct JSON mode

```bash
python run_analysis.py --rows-file recent_matches.json \
  --home-team-id 10 --away-team-id 20 --context-file context.json
```

`context.json` may contain `home_context`, `away_context`, `match_context` and
`h2h_rows`. In worker/SQLite mode use `--db`, `--match-id`, `--run-id`, the two
team IDs and a mandatory `--cutoff`. The cutoff is applied to both team history
and H2H data to prevent leakage.

## Autonomous free/local operation

The project contains the complete autonomous queue flow: `ResearchWorker`
performs search → source selection → crawl → evidence → claims, while the
SQLite worker handles statistics, Ollama synthesis, audit, retries and
recovery. No paid API is required. Live team information still needs an
internet connection and a local SearXNG instance; without it the system reports
missing evidence instead of inventing facts.

For live sports pages without publication metadata, the cutoff layer retains
the result as `UNVERIFIED_DATE`, applies a confidence penalty to derived claims,
and records an audit warning. Sources explicitly published after the cutoff are
still rejected. This avoids turning ordinary official club pages into a false
`UNRESOLVED` result.

For the supplied 8GB Linux Mint notebook, run `./scripts/run_local.sh` for the
local API and worker, and `python scripts/preflight.py` to inspect optional
SearXNG/Ollama availability. Ollama defaults to `qwen2.5:3b` and can be changed
with `OLLAMA_MODEL`; the heavier 7B model is not the default. See
`docs/NOTEBOOK_SETUP.md` for the Note 9 Termux worker and LAN setup.
The default Ollama timeout is 60 seconds with one attempt; if Ollama is
offline, the AI layer is reported as `insufficient_data` while the statistical
exact-score prediction and audit still complete. The AI prompt is bounded by
`FAE_AI_MAX_CLAIMS`, `FAE_AI_MAX_EVIDENCE_PER_CLAIM` and
`FAE_AI_MAX_EXCERPT_CHARS` for 8GB notebooks.

For a clean installation, follow `docs/COMPLETE_SETUP_RUNBOOK.md` from top to
bottom. It also documents the required historical-results bootstrap using
`scripts/import_history_csv.py`; a clean database cannot calculate form or an
exact score until historical results have been imported.

With `FAE_AUTO_HISTORY=1` the statistics worker automatically discovers and
caches structured public seasons from the openfootball catalogue when a team
has fewer than five historical matches. Tipsport remains a research/current-
results source; its public dynamic results page is not treated as a stable
multi-season historical API. Unsupported competitions can provide direct JSON
sources through `FAE_HISTORY_SOURCE_URLS` or use the CSV importer.
