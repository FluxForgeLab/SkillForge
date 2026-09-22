-- SkillForge core schema (system of record). No full-text virtual tables (R12).

CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY NOT NULL,
    name TEXT NOT NULL,
    description TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS source_documents (
    id TEXT PRIMARY KEY NOT NULL,
    project_id TEXT NOT NULL,
    filename TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    version TEXT NOT NULL,
    parser TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (project_id) REFERENCES projects (id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS chunks (
    id TEXT PRIMARY KEY NOT NULL,
    document_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    ordinal INTEGER NOT NULL,
    text TEXT NOT NULL,
    title TEXT,
    page INTEGER,
    line_start INTEGER,
    line_end INTEGER,
    FOREIGN KEY (document_id) REFERENCES source_documents (id) ON DELETE CASCADE,
    FOREIGN KEY (project_id) REFERENCES projects (id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS knowledge_units (
    id TEXT PRIMARY KEY NOT NULL,
    document_id TEXT NOT NULL,
    type TEXT NOT NULL,
    content TEXT NOT NULL,
    source_location TEXT,
    confidence REAL,
    FOREIGN KEY (document_id) REFERENCES source_documents (id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS skills (
    id TEXT PRIMARY KEY NOT NULL,
    project_id TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT,
    current_version_id TEXT,
    FOREIGN KEY (project_id) REFERENCES projects (id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS skill_versions (
    id TEXT PRIMARY KEY NOT NULL,
    skill_id TEXT NOT NULL,
    version TEXT NOT NULL,
    parent_version_id TEXT,
    status TEXT NOT NULL,
    artifact_path TEXT,
    manifest_hash TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (skill_id) REFERENCES skills (id) ON DELETE CASCADE,
    FOREIGN KEY (parent_version_id) REFERENCES skill_versions (id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS eval_cases (
    id TEXT PRIMARY KEY NOT NULL,
    skill_id TEXT NOT NULL,
    fixture TEXT NOT NULL,
    task TEXT NOT NULL,
    expected TEXT NOT NULL,
    forbidden TEXT NOT NULL,
    FOREIGN KEY (skill_id) REFERENCES skills (id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS evaluation_runs (
    id TEXT PRIMARY KEY NOT NULL,
    skill_version_id TEXT NOT NULL,
    baseline TEXT NOT NULL,
    metrics TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    FOREIGN KEY (skill_version_id) REFERENCES skill_versions (id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS eval_seals (
    skill_version_id TEXT PRIMARY KEY NOT NULL,
    evals_sha256 TEXT NOT NULL,
    FOREIGN KEY (skill_version_id) REFERENCES skill_versions (id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS eval_cache (
    version_hash TEXT NOT NULL,
    case_id TEXT NOT NULL,
    arm TEXT NOT NULL,
    model TEXT NOT NULL,
    payload TEXT NOT NULL,
    PRIMARY KEY (version_hash, case_id, arm, model)
);

CREATE TABLE IF NOT EXISTS trace_events (
    id TEXT PRIMARY KEY NOT NULL,
    run_id TEXT NOT NULL,
    type TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    payload TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS agent_runs (
    id TEXT PRIMARY KEY NOT NULL,
    status TEXT NOT NULL,
    final_content TEXT,
    steps INTEGER NOT NULL,
    tool_errors INTEGER NOT NULL,
    tokens INTEGER NOT NULL,
    latency_ms INTEGER NOT NULL,
    policy_violations INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_source_documents_project_id ON source_documents (project_id);

CREATE INDEX IF NOT EXISTS idx_chunks_document_id ON chunks (document_id);
CREATE INDEX IF NOT EXISTS idx_chunks_project_id ON chunks (project_id);

CREATE INDEX IF NOT EXISTS idx_knowledge_units_document_id ON knowledge_units (document_id);

CREATE INDEX IF NOT EXISTS idx_skills_project_id ON skills (project_id);

CREATE INDEX IF NOT EXISTS idx_skill_versions_skill_id ON skill_versions (skill_id);
CREATE INDEX IF NOT EXISTS idx_skill_versions_status ON skill_versions (status);

CREATE INDEX IF NOT EXISTS idx_eval_cases_skill_id ON eval_cases (skill_id);

CREATE INDEX IF NOT EXISTS idx_evaluation_runs_skill_version_id ON evaluation_runs (skill_version_id);

CREATE INDEX IF NOT EXISTS idx_trace_events_run_id ON trace_events (run_id);
CREATE INDEX IF NOT EXISTS idx_trace_events_timestamp ON trace_events (timestamp);
