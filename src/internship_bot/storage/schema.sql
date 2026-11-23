CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY,
    canonical_key TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    company TEXT NOT NULL,
    location TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    apply_url TEXT NOT NULL,
    posted_at TEXT,
    stipend_inr_per_month REAL,
    remote INTEGER NOT NULL CHECK (remote IN (0, 1)),
    internship INTEGER NOT NULL CHECK (internship IN (0, 1)),
    india_eligible INTEGER CHECK (india_eligible IN (0, 1)),
    score REAL NOT NULL DEFAULT 0,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'closed')),
    sent_at TEXT
);

CREATE TABLE IF NOT EXISTS source_listings (
    source TEXT NOT NULL,
    source_id TEXT NOT NULL,
    job_id INTEGER NOT NULL REFERENCES jobs(id),
    apply_url TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    PRIMARY KEY (source, source_id)
);

CREATE TABLE IF NOT EXISTS fx_rates (
    currency TEXT PRIMARY KEY,
    inr_rate REAL NOT NULL,
    fetched_on TEXT NOT NULL,
    rate_source TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS source_runs (
    id INTEGER PRIMARY KEY,
    source TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL CHECK (status IN ('success', 'failed', 'skipped')),
    raw_count INTEGER,
    error TEXT
);

CREATE INDEX IF NOT EXISTS idx_jobs_unsent ON jobs(status, sent_at, score);
CREATE INDEX IF NOT EXISTS idx_source_runs_recent ON source_runs(source, started_at DESC);
