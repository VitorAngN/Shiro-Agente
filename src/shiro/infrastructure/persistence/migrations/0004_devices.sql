-- 0004 · aparelhos pareados (ADR-0022): cada um com a própria chave
-- Só o SHA-256 da chave é guardado; a chave fica no aparelho.

CREATE TABLE device (
    id            TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    token_hash    TEXT NOT NULL UNIQUE,
    created_at    TEXT NOT NULL,
    last_seen_at  TEXT,
    revoked_at    TEXT
);
