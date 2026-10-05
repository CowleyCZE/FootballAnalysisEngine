PRAGMA foreign_keys = ON;

-- Systémové informace (z ČÁSTI 1)
CREATE TABLE IF NOT EXISTS system_info (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT NOT NULL UNIQUE,
    value TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Soutěže
CREATE TABLE IF NOT EXISTS competitions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    country TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Analytické běhy
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

-- Pipeline běhy (Stavový automat orchestrátoru)
CREATE TABLE IF NOT EXISTS pipeline_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL UNIQUE,
    match_id INTEGER,
    state TEXT NOT NULL,
    cycle INTEGER NOT NULL DEFAULT 0,
    max_cycles INTEGER NOT NULL DEFAULT 3,
    started_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    finished_at TEXT,
    error_text TEXT
);

-- Historie přechodů stavů pipeline
CREATE TABLE IF NOT EXISTS pipeline_state_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    old_state TEXT,
    new_state TEXT NOT NULL,
    reason TEXT,
    created_at TEXT NOT NULL
);

-- Fronta úloh (Jobs)
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL UNIQUE,
    run_id INTEGER,
    match_id INTEGER,
    job_type TEXT NOT NULL,
    status TEXT NOT NULL,
    priority INTEGER NOT NULL DEFAULT 50,
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    worker_id TEXT,
    parent_job_id INTEGER,
    payload_json TEXT,
    result_json TEXT,
    fingerprint TEXT,
    heartbeat_at TEXT,
    error TEXT,
    error_text TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    started_at TEXT,
    finished_at TEXT,
    FOREIGN KEY (run_id) REFERENCES runs(id)
);

-- Závislosti úloh
CREATE TABLE IF NOT EXISTS job_dependencies (
    job_id INTEGER NOT NULL,
    depends_on_job_id INTEGER NOT NULL,
    PRIMARY KEY (job_id, depends_on_job_id),
    FOREIGN KEY (job_id) REFERENCES jobs(id),
    FOREIGN KEY (depends_on_job_id) REFERENCES jobs(id)
);

-- Týmy
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

-- Hráči
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

-- Zápasy
CREATE TABLE IF NOT EXISTS matches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    external_match_id TEXT,
    competition TEXT,
    competition_id INTEGER,
    season TEXT,
    home_team_id INTEGER NOT NULL,
    away_team_id INTEGER NOT NULL,
    scheduled_at TEXT,
    status TEXT,
    venue TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (home_team_id) REFERENCES teams(id),
    FOREIGN KEY (away_team_id) REFERENCES teams(id),
    FOREIGN KEY (competition_id) REFERENCES competitions(id)
);

-- Zdroje informací
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

-- Dokumenty (Stažené HTML / zprávy)
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

-- Tvrzení (Claims)
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

-- Důkazy (Evidence)
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

-- Vazební tabulka Claim <-> Evidence
CREATE TABLE IF NOT EXISTS claim_evidence (
    claim_id INTEGER NOT NULL,
    evidence_id INTEGER NOT NULL,
    relationship TEXT NOT NULL DEFAULT 'SUPPORTS',
    weight REAL DEFAULT 1.0,
    PRIMARY KEY (claim_id, evidence_id),
    FOREIGN KEY (claim_id) REFERENCES claims(id),
    FOREIGN KEY (evidence_id) REFERENCES evidence(id)
);

-- TABULKA PRO PRIMÁRNÍ STATISTIKY ZÁPASU
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

-- TABULKA PRO STATISTICKÉ SNAPSHOTY (VÝSLEDKY ENGINE)
CREATE TABLE IF NOT EXISTS statistical_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
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

-- AI běhy
CREATE TABLE IF NOT EXISTS ai_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    match_id INTEGER,
    model TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    input_hash TEXT NOT NULL,
    output_hash TEXT,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    raw_response TEXT
);

-- Auditní tabulky
CREATE TABLE IF NOT EXISTS audit_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    audit_id TEXT,
    run_id TEXT,
    match_id INTEGER,
    ai_run_id TEXT,
    audit_score REAL,
    status TEXT NOT NULL,
    missing_data_count INTEGER NOT NULL DEFAULT 0,
    issues_count INTEGER NOT NULL DEFAULT 0,
    coverage_score REAL NOT NULL DEFAULT 0.0,
    executed_at TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS audit_issues (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    audit_id TEXT,
    audit_run_id INTEGER,
    rule_name TEXT,
    issue_type TEXT,
    severity TEXT NOT NULL,
    message TEXT,
    description TEXT,
    details_json TEXT,
    requires_research INTEGER NOT NULL DEFAULT 0,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS audit_issue_evidence (
    audit_issue_id INTEGER NOT NULL,
    evidence_id INTEGER NOT NULL,
    PRIMARY KEY (audit_issue_id, evidence_id)
);

CREATE TABLE IF NOT EXISTS audit_issue_claims (
    audit_issue_id INTEGER NOT NULL,
    claim_id INTEGER NOT NULL,
    PRIMARY KEY (audit_issue_id, claim_id)
);

-- Registry workerů
CREATE TABLE IF NOT EXISTS workers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    worker_id TEXT NOT NULL UNIQUE,
    worker_type TEXT,
    status TEXT NOT NULL DEFAULT 'IDLE',
    last_heartbeat TEXT,
    registered_at TEXT NOT NULL
);

-- Indexy pro rychlé vyhledávání
CREATE INDEX IF NOT EXISTS idx_documents_content_hash ON documents(content_hash);
CREATE INDEX IF NOT EXISTS idx_documents_canonical_url ON documents(canonical_url);
CREATE INDEX IF NOT EXISTS idx_documents_published_at ON documents(published_at);
CREATE INDEX IF NOT EXISTS idx_claims_run ON claims(run_id);
CREATE INDEX IF NOT EXISTS idx_claims_match ON claims(match_id);
CREATE INDEX IF NOT EXISTS idx_claims_status ON claims(status);
CREATE INDEX IF NOT EXISTS idx_evidence_document ON evidence(document_id);
CREATE INDEX IF NOT EXISTS idx_jobs_match ON jobs(match_id);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_match_statistics_match ON match_statistics(match_id);
CREATE INDEX IF NOT EXISTS idx_matches_scheduled_at ON matches(scheduled_at);
