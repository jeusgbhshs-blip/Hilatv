-- HiLatv gateway tables (T03). Portable across PostgreSQL and SQLite.
-- Independent of the T02 business migration head. Fold into Alembic as the
-- next revision when that framework is on main.

CREATE TABLE IF NOT EXISTS gateway_schema_migrations (
    version TEXT PRIMARY KEY,
    applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS call_logs (
    id TEXT PRIMARY KEY,
    seq BIGINT NOT NULL,
    created_at TEXT NOT NULL,
    day TEXT NOT NULL,
    project_id TEXT,
    node TEXT,
    shot_id TEXT,
    attempt INTEGER,
    task TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    params TEXT NOT NULL,
    latency_ms INTEGER NOT NULL,
    cost_cny TEXT NOT NULL,
    status TEXT NOT NULL,
    cache_hit INTEGER NOT NULL DEFAULT 0,
    qa_score TEXT,
    live INTEGER NOT NULL DEFAULT 0,
    fallback_reason TEXT,
    output TEXT,
    error TEXT
);

CREATE INDEX IF NOT EXISTS call_logs_day_idx ON call_logs (day);
CREATE INDEX IF NOT EXISTS call_logs_seq_idx ON call_logs (seq);

CREATE TABLE IF NOT EXISTS alerts (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    kind TEXT NOT NULL,
    message TEXT NOT NULL,
    spent_cny TEXT NOT NULL,
    limit_cny TEXT NOT NULL,
    daily_spent_cny TEXT,
    daily_limit_cny TEXT,
    details TEXT
);
