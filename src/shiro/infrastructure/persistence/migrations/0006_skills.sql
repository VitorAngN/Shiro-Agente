-- 0006 · habilidades montadas pela SHIRO a pedido do usuário (ADR-0025)

CREATE TABLE skill (
    name         TEXT PRIMARY KEY,
    description  TEXT NOT NULL,
    steps        TEXT NOT NULL,  -- JSON: [{"tool": ..., "args": {...}}]
    created_at   TEXT NOT NULL
);
