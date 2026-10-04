PRAGMA foreign_keys = ON;

-- Research orchestration tables. Core provenance tables
-- (runs, claims, evidence, documents, sources, claim_evidence) live in schema.sql.
CREATE TABLE IF NOT EXISTS research_tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    run_db_id INTEGER,
    match_id INTEGER NOT NULL,
    task_uuid TEXT NOT NULL,
    domain TEXT NOT NULL,
    task_type TEXT NOT NULL,
    description TEXT NOT NULL,
    required INTEGER NOT NULL DEFAULT 0,
    priority INTEGER NOT NULL DEFAULT 50,
    capabilities_json TEXT NOT NULL DEFAULT '[]',
    data_cutoff_at TEXT NOT NULL,
    home_team TEXT NOT NULL,
    away_team TEXT NOT NULL,
    competition TEXT NOT NULL,
    scheduled_at TEXT NOT NULL,
    venue TEXT,
    status TEXT NOT NULL DEFAULT 'PLANNED',
    attempt_number INTEGER NOT NULL DEFAULT 1,
    job_id TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(run_id, task_uuid),
    FOREIGN KEY (run_db_id) REFERENCES runs(id),
    FOREIGN KEY (job_id) REFERENCES jobs(job_id)
);

CREATE INDEX IF NOT EXISTS idx_research_tasks_run ON research_tasks(run_id);
CREATE INDEX IF NOT EXISTS idx_research_tasks_status ON research_tasks(run_id, status);
CREATE INDEX IF NOT EXISTS idx_research_tasks_match ON research_tasks(match_id);
CREATE INDEX IF NOT EXISTS idx_research_tasks_job ON research_tasks(job_id);

CREATE TABLE IF NOT EXISTS research_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_uuid TEXT NOT NULL UNIQUE,
    run_id INTEGER NOT NULL,
    task_id INTEGER NOT NULL,
    strategy TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    status TEXT NOT NULL,
    FOREIGN KEY (run_id) REFERENCES runs(id),
    FOREIGN KEY (task_id) REFERENCES research_tasks(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS research_queries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    query TEXT NOT NULL,
    query_type TEXT NOT NULL,
    query_hash TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    result_count INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (session_id) REFERENCES research_sessions(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS source_candidates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    url TEXT NOT NULL,
    domain TEXT NOT NULL,
    source_type TEXT,
    source_score REAL,
    selected INTEGER NOT NULL DEFAULT 0,
    rejection_reason TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES research_sessions(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS research_executions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    execution_uuid TEXT NOT NULL UNIQUE,
    task_id INTEGER NOT NULL,
    attempt_number INTEGER NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    error_message TEXT,
    FOREIGN KEY (task_id) REFERENCES research_tasks(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_research_sessions_task ON research_sessions(task_id);
CREATE INDEX IF NOT EXISTS idx_research_queries_session ON research_queries(session_id);
CREATE INDEX IF NOT EXISTS idx_source_candidates_session ON source_candidates(session_id);
CREATE INDEX IF NOT EXISTS idx_research_executions_task ON research_executions(task_id);
