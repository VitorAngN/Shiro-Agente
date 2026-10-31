# ADR-0007 · SQLite para persistência

- **Status:** Aceito
- **Data:** 2026-10-30

## Contexto

O SHIRO precisa guardar conversas, chamadas de ferramenta, auditoria, memórias com busca por similaridade, lembretes e uso dos provedores. Um usuário, um PC, volume pequeno (milhares de linhas por mês), e tudo precisa funcionar offline e sem serviços extras para manter.

## Decisão

- **SQLite** em um único arquivo, modo **WAL**, acessado com `aiosqlite`.
- **SQL explícito** em repositórios (`persistence/`), sem ORM.
- Busca vetorial com a extensão **`sqlite-vec`** e embeddings gerados localmente pelo Ollama.
- Migrações SQL numeradas, versão em `PRAGMA user_version`, backup automático antes de migrar.

## Alternativas consideradas

| Alternativa | Por que não |
|---|---|
| PostgreSQL (+ pgvector) | Excelente, mas é um serviço a mais para instalar e manter no Windows, sem necessidade neste volume |
| Arquivos JSON | Sem transações, sem consultas, corrompe fácil em queda de energia |
| Banco vetorial dedicado (Chroma, Qdrant) | Dependência e processo extras para poucas centenas de memórias |
| ORM (SQLAlchemy) | Útil em esquemas grandes; aqui o esquema é pequeno e SQL explícito é mais transparente |

## Consequências

- ✅ Zero infraestrutura: backup é copiar um arquivo.
- ✅ Funciona offline e é rápido para este volume.
- ✅ Tudo (dados, vetores, auditoria) em um lugar só, com transações.
- ⚠️ Escrita concorrente limitada. Irrelevante com um processo; o WAL permite leitura pelo painel enquanto o SHIRO escreve.
- ⚠️ `sqlite-vec` é uma extensão nativa: precisa ser carregada e testada no Windows na CI.
