-- 0001 · conversas, chamadas de ferramenta, auditoria e uso de provedores
-- Modelo descrito em docs/04-modelo-de-dados.md.

CREATE TABLE session (
    id          TEXT PRIMARY KEY,
    channel     TEXT NOT NULL CHECK (channel IN ('text', 'voice', 'api', 'scheduler')),
    started_at  TEXT NOT NULL,
    ended_at    TEXT
);

CREATE TABLE message (
    id          TEXT PRIMARY KEY,
    session_id  TEXT NOT NULL REFERENCES session (id),
    trace_id    TEXT NOT NULL,
    role        TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content     TEXT NOT NULL,
    tier        TEXT CHECK (tier IN ('T0', 'T1', 'T2')),
    provider    TEXT,
    model       TEXT,
    tokens_in   INTEGER,
    tokens_out  INTEGER,
    latency_ms  INTEGER,
    created_at  TEXT NOT NULL
);
CREATE INDEX ix_message_session ON message (session_id, created_at);
CREATE INDEX ix_message_trace ON message (trace_id);

CREATE TABLE tool_call (
    id              TEXT PRIMARY KEY,
    message_id      TEXT NOT NULL REFERENCES message (id),
    tool_name       TEXT NOT NULL,
    args_json       TEXT NOT NULL,
    risk            TEXT CHECK (risk IN ('R0', 'R1', 'R2', 'R3', 'R4')),
    decision        TEXT NOT NULL CHECK (decision IN ('allow', 'confirmed', 'denied', 'blocked')),
    status          TEXT NOT NULL CHECK (status IN ('ok', 'error', 'skipped')),
    result_summary  TEXT,
    duration_ms     INTEGER,
    finished_at     TEXT NOT NULL
);
CREATE INDEX ix_tool_call_message ON tool_call (message_id);

-- Auditoria append-only com hash encadeado (docs/05-seguranca.md, ameaça A-10).
CREATE TABLE audit_event (
    seq           INTEGER PRIMARY KEY AUTOINCREMENT,
    ts            TEXT NOT NULL,
    trace_id      TEXT NOT NULL,
    event_type    TEXT NOT NULL,
    payload_json  TEXT NOT NULL,
    prev_hash     TEXT NOT NULL,
    hash          TEXT NOT NULL
);
CREATE INDEX ix_audit_trace ON audit_event (trace_id);

CREATE TRIGGER audit_event_no_update
BEFORE UPDATE ON audit_event
BEGIN
    SELECT RAISE(ABORT, 'audit_event é append-only');
END;

-- Só a retenção pode apagar, e só eventos com mais de 365 dias.
CREATE TRIGGER audit_event_no_recent_delete
BEFORE DELETE ON audit_event
WHEN julianday('now') - julianday(old.ts) < 365
BEGIN
    SELECT RAISE(ABORT, 'audit_event é append-only');
END;

CREATE TABLE provider_usage (
    day           TEXT NOT NULL,
    provider      TEXT NOT NULL,
    model         TEXT NOT NULL,
    requests      INTEGER NOT NULL DEFAULT 0,
    tokens_in     INTEGER NOT NULL DEFAULT 0,
    tokens_out    INTEGER NOT NULL DEFAULT 0,
    est_cost_usd  REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (day, provider, model)
);
