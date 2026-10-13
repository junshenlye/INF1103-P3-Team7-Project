-- Stackplan's complete assignment-scale PostgreSQL schema.
-- Docker applies this file only when it creates a fresh database volume.

CREATE TABLE IF NOT EXISTS projects (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    week_count INTEGER NOT NULL DEFAULT 14 CHECK (week_count BETWEEN 1 AND 52),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS pipeline_runs (
    id BIGSERIAL PRIMARY KEY,
    project_id BIGINT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'running'
        CHECK (status IN ('running', 'completed', 'partial', 'failed')),
    requested_module_count INTEGER NOT NULL DEFAULT 0 CHECK (requested_module_count >= 0),
    processed_module_count INTEGER NOT NULL DEFAULT 0 CHECK (processed_module_count >= 0),
    result_payload JSONB,
    errors JSONB NOT NULL DEFAULT '[]'::JSONB,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS recommendations (
    id BIGSERIAL PRIMARY KEY,
    project_id BIGINT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    recommendation_type TEXT NOT NULL
        CHECK (recommendation_type IN ('work_checklist', 'trimester_revision_plan')),
    input_revision_hash TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    model_name TEXT NOT NULL,
    preferences JSONB NOT NULL DEFAULT '{}'::JSONB,
    recommendation_payload JSONB NOT NULL,
    status TEXT NOT NULL DEFAULT 'candidate'
        CHECK (status IN ('candidate', 'accepted', 'dismissed')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS recommendation_project_lookup
    ON recommendations(project_id, recommendation_type, created_at DESC);
