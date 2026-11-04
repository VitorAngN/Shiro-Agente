-- 0003 · memória de longo prazo: fatos que o usuário pediu para lembrar (RF-41 a RF-44)
-- O vetor fica em tabela separada para trocar o modelo de embedding e reindexar
-- sem perder os fatos (docs/04-modelo-de-dados.md).

CREATE TABLE memory_fact (
    id            TEXT PRIMARY KEY,
    content       TEXT NOT NULL,
    category      TEXT NOT NULL DEFAULT 'outro'
                  CHECK (category IN ('preferencia', 'pessoa', 'projeto', 'outro')),
    source        TEXT NOT NULL DEFAULT 'explicit',
    local_only    INTEGER NOT NULL DEFAULT 1,
    created_at    TEXT NOT NULL,
    last_used_at  TEXT
);

CREATE TABLE memory_embedding (
    fact_id  TEXT PRIMARY KEY REFERENCES memory_fact (id) ON DELETE CASCADE,
    vector   BLOB NOT NULL,
    model    TEXT NOT NULL
);
