PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS system_info (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT NOT NULL UNIQUE,
    value TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    pipeline_version TEXT,
    config_hash TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS pipeline_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL UNIQUE,
    match_id INTEGER,
    state TEXT NOT NULL,
    cycle INTEGER NOT NULL DEFAULT 1,
    max_cycles INTEGER NOT NULL DEFAULT 3,
    started_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    finished_at TEXT,
    error_text TEXT
);

CREATE TABLE IF NOT EXISTS workers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    worker_id TEXT NOT NULL UNIQUE,
    worker_type TEXT NOT NULL DEFAULT 'generic',
    status TEXT NOT NULL DEFAULT 'OFFLINE',
    capabilities_json TEXT NOT NULL DEFAULT '[]',
    last_heartbeat TEXT,
    current_job_id TEXT,
    metadata_json TEXT,
    registered_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL UNIQUE,
    run_id TEXT,
    match_id INTEGER,
    parent_job_id INTEGER,
    job_type TEXT NOT NULL,
    status TEXT NOT NULL,
    priority INTEGER NOT NULL DEFAULT 50,
    payload_json TEXT,
    result_json TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    worker_id TEXT,
    fingerprint TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    started_at TEXT,
    finished_at TEXT,
    heartbeat_at TEXT,
    next_attempt_at TEXT,
    error_text TEXT,
    FOREIGN KEY (parent_job_id) REFERENCES jobs(id),
    FOREIGN KEY (worker_id) REFERENCES workers(worker_id)
);

CREATE TABLE IF NOT EXISTS job_dependencies (
    job_id INTEGER NOT NULL,
    depends_on_job_id INTEGER NOT NULL,
    PRIMARY KEY (job_id, depends_on_job_id),
    FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE,
    FOREIGN KEY (depends_on_job_id) REFERENCES jobs(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS pipeline_state_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    old_state TEXT,
    new_state TEXT NOT NULL,
    reason TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS system_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    run_id TEXT,
    job_id TEXT,
    worker_id TEXT,
    payload_json TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS teams (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    normalized_name TEXT NOT NULL UNIQUE,
    country TEXT,
    competition TEXT,
    external_ids_json TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS players (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    normalized_name TEXT NOT NULL,
    team_id INTEGER,
    position TEXT,
    shirt_number INTEGER,
    external_ids_json TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (team_id) REFERENCES teams(id)
);

CREATE TABLE IF NOT EXISTS matches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    external_match_id TEXT,
    competition TEXT NOT NULL,
    season TEXT,
    home_team_id INTEGER NOT NULL,
    away_team_id INTEGER NOT NULL,
    scheduled_at TEXT,
    status TEXT,
    venue TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (home_team_id) REFERENCES teams(id),
    FOREIGN KEY (away_team_id) REFERENCES teams(id)
);

CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    domain TEXT NOT NULL UNIQUE,
    name TEXT,
    source_type TEXT,
    priority INTEGER NOT NULL DEFAULT 50,
    reliability_score REAL,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id INTEGER,
    url TEXT NOT NULL,
    canonical_url TEXT,
    content_hash TEXT NOT NULL,
    title TEXT,
    description TEXT,
    author TEXT,
    language TEXT,
    published_at TEXT,
    modified_at TEXT,
    retrieved_at TEXT NOT NULL,
    content_type TEXT,
    content_length INTEGER,
    raw_path TEXT,
    processed_path TEXT,
    parser_version TEXT,
    quality_score REAL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (source_id) REFERENCES sources(id)
);

CREATE TABLE IF NOT EXISTS claims (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER,
    match_id INTEGER,
    claim_text TEXT NOT NULL,
    claim_type TEXT,
    normalized_claim TEXT,
    status TEXT NOT NULL DEFAULT 'UNVERIFIED',
    confidence REAL,
    valid_from TEXT,
    valid_until TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (run_id) REFERENCES runs(id),
    FOREIGN KEY (match_id) REFERENCES matches(id)
);

CREATE TABLE IF NOT EXISTS evidence (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER NOT NULL,
    evidence_type TEXT NOT NULL,
    quoted_text TEXT,
    extracted_value TEXT,
    locator TEXT,
    extraction_method TEXT,
    confidence REAL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (document_id) REFERENCES documents(id)
);

CREATE TABLE IF NOT EXISTS claim_evidence (
    claim_id INTEGER NOT NULL,
    evidence_id INTEGER NOT NULL,
    relationship TEXT NOT NULL DEFAULT 'SUPPORTS',
    weight REAL DEFAULT 1.0,
    PRIMARY KEY (claim_id, evidence_id),
    FOREIGN KEY (claim_id) REFERENCES claims(id),
    FOREIGN KEY (evidence_id) REFERENCES evidence(id)
);

CREATE TABLE IF NOT EXISTS match_statistics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id INTEGER NOT NULL UNIQUE,
    home_goals INTEGER,
    away_goals INTEGER,
    home_ht_goals INTEGER,
    away_ht_goals INTEGER,
    home_ft_goals INTEGER,
    away_ft_goals INTEGER,
    home_shots INTEGER,
    away_shots INTEGER,
    home_shots_on_target INTEGER,
    away_shots_on_target INTEGER,
    home_possession REAL,
    away_possession REAL,
    home_corners INTEGER,
    away_corners INTEGER,
    home_yellow_cards INTEGER,
    away_yellow_cards INTEGER,
    home_red_cards INTEGER,
    away_red_cards INTEGER,
    home_xg REAL,
    away_xg REAL,
    home_xga REAL,
    away_xga REAL,
    home_npxg REAL,
    away_npxg REAL,
    xg_metric_definition TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (match_id) REFERENCES matches(id)
);

CREATE TABLE IF NOT EXISTS statistical_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER,
    match_id INTEGER,
    team_id INTEGER,
    metric TEXT NOT NULL,
    value REAL,
    sample_size INTEGER,
    coverage REAL,
    data_cutoff_at TEXT NOT NULL,
    calculation_version TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (run_id) REFERENCES runs(id),
    FOREIGN KEY (match_id) REFERENCES matches(id),
    FOREIGN KEY (team_id) REFERENCES teams(id)
);

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
    FOREIGN KEY (match_id) REFERENCES matches(id),
    FOREIGN KEY (job_id) REFERENCES jobs(job_id)
);

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

CREATE INDEX IF NOT EXISTS idx_jobs_queue ON jobs(status, priority DESC, id);
CREATE INDEX IF NOT EXISTS idx_jobs_match ON jobs(match_id);
CREATE INDEX IF NOT EXISTS idx_jobs_run ON jobs(run_id);
CREATE INDEX IF NOT EXISTS idx_jobs_worker ON jobs(worker_id);
CREATE INDEX IF NOT EXISTS idx_jobs_heartbeat ON jobs(status, heartbeat_at);
CREATE INDEX IF NOT EXISTS idx_jobs_fingerprint ON jobs(fingerprint, status);
CREATE INDEX IF NOT EXISTS idx_pipeline_runs_match ON pipeline_runs(match_id);
CREATE INDEX IF NOT EXISTS idx_pipeline_state_history_run ON pipeline_state_history(run_id);
CREATE INDEX IF NOT EXISTS idx_system_events_run ON system_events(run_id);
CREATE INDEX IF NOT EXISTS idx_documents_content_hash ON documents(content_hash);
CREATE INDEX IF NOT EXISTS idx_documents_canonical_url ON documents(canonical_url);
CREATE INDEX IF NOT EXISTS idx_documents_published_at ON documents(published_at);
CREATE INDEX IF NOT EXISTS idx_claims_run ON claims(run_id);
CREATE INDEX IF NOT EXISTS idx_claims_match ON claims(match_id);
CREATE INDEX IF NOT EXISTS idx_evidence_document ON evidence(document_id);
CREATE INDEX IF NOT EXISTS idx_matches_scheduled_at ON matches(scheduled_at);
CREATE INDEX IF NOT EXISTS idx_research_tasks_run ON research_tasks(run_id);
CREATE INDEX IF NOT EXISTS idx_research_tasks_status ON research_tasks(run_id, status);
CREATE INDEX IF NOT EXISTS idx_research_tasks_match ON research_tasks(match_id);
CREATE INDEX IF NOT EXISTS idx_research_tasks_job ON research_tasks(job_id);
CREATE INDEX IF NOT EXISTS idx_research_sessions_task ON research_sessions(task_id);
CREATE INDEX IF NOT EXISTS idx_research_queries_session ON research_queries(session_id);
CREATE INDEX IF NOT EXISTS idx_source_candidates_session ON source_candidates(session_id);
CREATE INDEX IF NOT EXISTS idx_research_executions_task ON research_executions(task_id);
