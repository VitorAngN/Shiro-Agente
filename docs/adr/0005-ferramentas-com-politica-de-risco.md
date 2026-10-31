# ADR-0005 · Ferramentas com risco declarado e motor de políticas

- **Status:** Aceito
- **Data:** 2026-10-30

## Contexto

O modelo de linguagem decide quais ferramentas chamar. Ele pode errar (alucinação) ou ser enganado (prompt injection via web, arquivos ou áudio de terceiros). Instruções no prompt do sistema ("nunca apague arquivos sem perguntar") não são garantia, porque o próprio modelo é quem as interpreta.

## Decisão

1. Toda ferramenta declara no `ToolSpec` seu **nível de risco** (R0–R4), se a saída é confiável (`output_trusted`) e se o resultado é sensível (`local_only`).
2. Um **`PolicyEngine`**, função pura fora do modelo, decide para cada chamada: `ALLOW`, `CONFIRM_VOICE`, `CONFIRM_PHYSICAL` ou `DENY`.
3. Conteúdo externo marca a sessão com **taint**, o que endurece a política até o fim do turno.
4. **Não existe ferramenta de terminal arbitrário.** Cada capacidade é uma ferramenta específica, com argumentos tipados.
5. Exclusões vão para a **lixeira do SHIRO**; apagar de verdade é R3.
6. Toda decisão é registrada na auditoria.

Regras completas em [05 · Segurança](../05-seguranca.md).

## Alternativas consideradas

| Alternativa | Por que não |
|---|---|
| Confiar só no prompt do sistema | O modelo é justamente a parte que pode ser enganada |
| Confirmar toda ação | Seguro, mas irritante: o usuário passa a confirmar sem ler, o que anula a proteção |
| Ferramenta genérica de shell com lista de bloqueio | Listas de bloqueio sempre têm brechas; ferramentas específicas têm superfície pequena e testável |

## Consequências

- ✅ Segurança verificável por testes, independente do modelo usado.
- ✅ Confirmações só onde importam, então continuam significativas.
- ⚠️ Cada capacidade nova exige uma ferramenta nova. É o preço da superfície pequena; o checklist de segurança mantém o processo leve.
- ⚠️ O taint pode pedir confirmações a mais em tarefas de pesquisa. Ajustável depois com base nos dados da auditoria.
