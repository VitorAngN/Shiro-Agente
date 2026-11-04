-- 0002 · atividades com prazo e trabalhos agendados (avisos e lembretes)
-- Datas em ISO 8601 UTC, comparáveis como texto. Ver ADR-0009.

CREATE TABLE activity (
    id            TEXT PRIMARY KEY,
    title         TEXT NOT NULL,
    context       TEXT,
    due_at        TEXT,
    due_text      TEXT,
    status        TEXT NOT NULL CHECK (status IN ('pending', 'done', 'cancelled')),
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    completed_at  TEXT
);
CREATE INDEX ix_activity_status_due ON activity (status, due_at);

CREATE TABLE scheduled_job (
    id            TEXT PRIMARY KEY,
    kind          TEXT NOT NULL CHECK (kind IN ('activity_alert', 'reminder')),
    ref_id        TEXT,
    payload_json  TEXT NOT NULL,
    run_at        TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'done', 'cancelled')),
    created_at    TEXT NOT NULL
);
CREATE INDEX ix_scheduled_job_due ON scheduled_job (status, run_at);
CREATE INDEX ix_scheduled_job_ref ON scheduled_job (ref_id, kind);
