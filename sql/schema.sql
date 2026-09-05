CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS profile (
    id SERIAL PRIMARY KEY,
    raw_cv_text TEXT NOT NULL,
    extracted_json JSONB NOT NULL,
    embedding VECTOR(384) NOT NULL,
    location_preference TEXT,
    remote_preference TEXT CHECK (remote_preference IN ('remote','hybrid','onsite','any')),
    role_family TEXT[] NOT NULL,
    min_salary INTEGER,
    excluded_keywords TEXT[],
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS job_offer (
    id SERIAL PRIMARY KEY,
    external_id TEXT UNIQUE NOT NULL,
    title TEXT NOT NULL,
    company TEXT,
    location TEXT,
    remote_type TEXT,
    description TEXT NOT NULL,
    apply_link TEXT NOT NULL,
    source TEXT NOT NULL,
    salary_min INTEGER,
    salary_max INTEGER,
    posted_at TIMESTAMPTZ,
    embedding VECTOR(384),
    fetched_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS job_score (
    id SERIAL PRIMARY KEY,
    job_offer_id INTEGER REFERENCES job_offer(id) ON DELETE CASCADE,
    profile_id INTEGER REFERENCES profile(id) ON DELETE CASCADE,
    vector_similarity FLOAT NOT NULL,
    llm_score INTEGER,
    llm_evaluated BOOLEAN DEFAULT FALSE,
    pros TEXT[],
    cons TEXT[],
    missing_requirements TEXT[],
    final_score FLOAT NOT NULL,
    status TEXT DEFAULT 'new' CHECK (status IN ('new','viewed','applied','discarded')),
    created_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(job_offer_id, profile_id)
);

CREATE TABLE IF NOT EXISTS run_log (
    id SERIAL PRIMARY KEY,
    started_at TIMESTAMPTZ DEFAULT now(),
    finished_at TIMESTAMPTZ,
    jsearch_calls_used INTEGER DEFAULT 0,
    llm_calls_used INTEGER DEFAULT 0,
    new_jobs_found INTEGER DEFAULT 0,
    errors TEXT
);

CREATE INDEX IF NOT EXISTS job_offer_embedding_idx ON job_offer USING ivfflat (embedding vector_cosine_ops);
