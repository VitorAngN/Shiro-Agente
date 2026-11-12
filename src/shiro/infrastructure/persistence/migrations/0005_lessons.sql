-- 0005 · lições do usuário (ADR-0023): "quando eu disser X, faça Y"

CREATE TABLE lesson (
    trigger     TEXT PRIMARY KEY,
    meaning     TEXT NOT NULL,
    created_at  TEXT NOT NULL
);
