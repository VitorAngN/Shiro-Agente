# 04 · Modelo de dados

Todo o estado persistente fica em um único arquivo SQLite (`%LOCALAPPDATA%\SHIRO\shiro.db`), em modo WAL, com migrações versionadas. Justificativa em [ADR-0007](adr/0007-sqlite-para-persistencia.md).

## 1. Diagrama entidade-relacionamento

```mermaid
erDiagram
    SESSION ||--o{ MESSAGE : contem
    MESSAGE ||--o{ TOOL_CALL : dispara
    TOOL_CALL ||--o| CONFIRMATION : exige
    TOOL_CALL ||--o| TRASH_ITEM : gera
    ROUTINE ||--o{ SCHEDULED_JOB : agenda
    ACTIVITY ||--o{ SCHEDULED_JOB : avisa
    TOOL_CALL ||--o| ACTIVITY : cria
    MEMORY_FACT ||--o| MEMORY_EMBEDDING : indexa

    SESSION {
        text id PK "UUIDv7"
        text channel "voice | text | api | scheduler"
        text started_at
        text ended_at
    }
    MESSAGE {
        text id PK
        text session_id FK
        text trace_id
        text role "user | assistant | tool"
        text content
        text tier "T0 | T1 | T2"
        text provider
        text model
        int tokens_in
        int tokens_out
        int latency_ms
        text created_at
    }
    TOOL_CALL {
        text id PK
        text message_id FK
        text tool_name
        text args_json
        text risk "R0..R4, nulo se a ferramenta não existe"
        text decision "allow | confirmed | denied | blocked"
        text status "ok | error | skipped"
        text result_summary
        int duration_ms
        text finished_at
    }
    CONFIRMATION {
        text id PK
        text tool_call_id FK
        text kind "voice | physical"
        text prompt
        text status "pending | approved | rejected | expired"
        text responded_at
    }
    TRASH_ITEM {
        text id PK
        text tool_call_id FK
        text original_path
        text trash_path
        int size_bytes
        text deleted_at
        text purge_after
    }
    MEMORY_FACT {
        text id PK
        text content
        text category "preferencia | pessoa | projeto | outro"
        text source "explicit"
        int local_only
        text created_at
        text last_used_at
    }
    MEMORY_EMBEDDING {
        text fact_id PK
        blob vector "sqlite-vec"
        text model
    }
    ACTIVITY {
        text id PK
        text title
        text context "disciplina ou projeto, opcional"
        text due_at "UTC, nulo se sem prazo"
        text due_text "expressão original, ex. sexta"
        text status "pending | done | cancelled"
        text created_at
        text updated_at
        text completed_at
    }
    ROUTINE {
        text id PK
        text name UK
        text steps_json
        int enabled
    }
    SCHEDULED_JOB {
        text id PK
        text kind "activity_alert | reminder (rotinas e timers: Fase 3)"
        text ref_id "atividade avisada, nulo em lembretes"
        text payload_json
        text run_at "UTC"
        text status "active | done | cancelled"
        text created_at
    }
    AUDIT_EVENT {
        int seq PK
        text ts
        text trace_id
        text event_type
        text payload_json
        text prev_hash
        text hash
    }
    PROVIDER_USAGE {
        text day PK
        text provider PK
        text model PK
        int requests
        int tokens_in
        int tokens_out
        real est_cost_usd
    }
```

`AUDIT_EVENT` e `PROVIDER_USAGE` não têm chave estrangeira de propósito: a auditoria precisa sobreviver mesmo se o histórico de conversas for apagado.

## 2. Decisões de modelagem

| Decisão | Motivo |
|---|---|
| IDs em **UUIDv7** | Ordenáveis por tempo, sem colisão, sem expor contagem |
| Datas em texto **ISO 8601 UTC** | Padrão do SQLite, legível e ordenável. Conversão para o fuso local só na interface |
| `args_json` e `payload_json` em JSON | Cada ferramenta tem argumentos diferentes. A validação acontece no Pydantic, não no banco |
| `MEMORY_EMBEDDING` separada de `MEMORY_FACT` | Permite trocar o modelo de embedding e reindexar sem perder os fatos |
| `AUDIT_EVENT` com **hash encadeado** | `hash = sha256(prev_hash + payload)`. Qualquer edição quebra a cadeia e é detectada na inicialização |
| `PROVIDER_USAGE` agregado por dia | Base do orçamento diário de nuvem (RNF-10) sem varrer o histórico |
| `ACTIVITY.due_text` guarda a expressão original | Permite auditar e testar o resolvedor de datas: "o que foi dito" versus "o que foi entendido" ([ADR-0009](adr/0009-voz-e-atividades-no-mvp.md)) |
| Avisos de atividade como `SCHEDULED_JOB` | Um único agendador para lembretes, rotinas e avisos; adiar uma atividade só reagenda os jobs ligados a ela |
| Gatilhos `UPDATE` e `DELETE` bloqueados em `AUDIT_EVENT` | A aplicação só consegue inserir |

## 3. Memória: o que entra e o que não entra

| Entra | Não entra |
|---|---|
| Fatos que eu peço explicitamente: "lembra que…" | Inferências do modelo sobre mim |
| Preferências de uso: apps favoritos, volume preferido, horários | Conteúdo de arquivos pessoais |
| Nomes de projetos e matérias, para dar contexto | Senhas, tokens, documentos, dados bancários |

`local_only = 1` impede que o fato seja incluído em um contexto enviado para a nuvem. O padrão para fatos novos é `1`, e o usuário libera caso a caso.

## 4. Retenção

| Dado | Retenção padrão | Configurável |
|---|---|---|
| Áudio | Não é gravado | Pode ser ativado para depuração, com expiração de 24 h |
| `SESSION`, `MESSAGE`, `TOOL_CALL` | 90 dias | Sim |
| `TRASH_ITEM` e arquivos na lixeira | 7 dias, depois limpeza definitiva | Sim |
| `MEMORY_FACT` | Até eu pedir para esquecer | — |
| `ACTIVITY` pendente | Até ser concluída ou excluída | — |
| `ACTIVITY` concluída ou cancelada | 1 ano | Sim |
| `AUDIT_EVENT` | 1 ano | Sim, mas nunca menos que o histórico de mensagens |
| Logs em arquivo | 5 arquivos de 10 MB, em rotação | Sim |

A limpeza roda como tarefa interna do agendador, uma vez por dia, e também é registrada na auditoria.

## 5. Migrações

Migrações SQL numeradas em `src/shiro/infrastructure/persistence/migrations/` (`0001_init.sql`, `0002_…`), aplicadas na inicialização dentro de uma transação, com a versão registrada em `PRAGMA user_version`. Antes de migrar, o SHIRO copia o banco para `shiro.db.bak`.
