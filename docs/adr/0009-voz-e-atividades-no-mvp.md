# ADR-0009 · Voz e atividades no MVP

- **Status:** Aceito
- **Data:** 2026-10-30

## Contexto

O roadmap original entregava o agente em texto (Fase 1) e só depois a voz (Fase 2). Ao revisar o escopo, ficou definido um requisito essencial: **poder pedir por voz**, tanto para o SHIRO **executar tarefas** ("abre o VS Code") quanto para **registrar atividades com prazo** ("anota o trabalho de cálculo pra sexta").

Sem voz, o MVP não resolve o problema principal. Sem atividades, ele não cobre um dos usos mais frequentes.

## Decisão

### 1. Voz e atividades entram na Fase 1

As antigas fases "Cérebro em texto" e "Voz" viram uma única **Fase 1 · MVP de voz**, entregue em três marcos testáveis separadamente: **1a** cérebro, **1b** voz, **1c** atividades. O modo texto continua existindo como ferramenta de depuração. As fases seguintes foram renumeradas (ver [Roadmap](../06-roadmap.md)).

### 2. Atividades são um módulo de domínio próprio

`shiro.activities` contém o modelo `Activity`, as regras (status, adiamento, avisos) e as ferramentas expostas ao agente. Ele depende só das portas do núcleo, e o núcleo não o conhece. Os avisos de prazo são agendados no `Scheduler` como `SCHEDULED_JOB` ligados à atividade.

### 3. Datas: o modelo extrai, o código resolve

Modelos de 8B erram com frequência em datas relativas ("sexta que vem", "depois de amanhã"). Por isso:

1. o LLM só **extrai** a expressão de prazo como texto ("sexta", "dia 12 às 23h59");
2. um resolvedor **determinístico** converte para data absoluta, relativa ao fuso configurado (candidato: biblioteca `dateparser`, que suporta português; validar no spike);
3. regras fixas e testadas:
   - só o dia, sem horário → 23h59 daquele dia;
   - dia da semana → próxima ocorrência futura;
   - expressão ambígua ou não reconhecida → o SHIRO pergunta, não chuta;
4. o SHIRO **sempre repete em voz alta** a data absoluta antes de salvar (RF-35).

### 4. Privacidade

Títulos de atividades podem conter dados pessoais. As ferramentas de atividades devolvem resultados com `local_only=True`, então perguntas sobre atividades são resolvidas no Tier 0 ou no Tier 1, sem sair do PC.

## Alternativas consideradas

| Alternativa | Por que não |
|---|---|
| Manter a ordem texto → voz | O MVP não atenderia o requisito principal. O risco de juntar as duas coisas é controlado pelos marcos 1a/1b/1c |
| Usar um app externo (Google Tasks, Notion) como fonte das atividades desde já | Exige internet e autenticação e quebra o funcionamento offline. Sincronização fica como RF-40, no futuro |
| Deixar o LLM resolver datas sozinho | Difícil de testar e propenso a erro em modelos pequenos. A resolução determinística tem testes de tabela |

## Consequências

- ✅ O MVP já resolve o uso principal: falar e o SHIRO agir ou anotar.
- ✅ Datas corretas e verificáveis por testes, com meta própria (RNF-16).
- ⚠️ A Fase 1 fica maior. Mitigação: marcos com critérios próprios e entregas incrementais no GitHub.
- ⚠️ Os spikes de modelo local e de VRAM acontecem na mesma fase. Mitigação: o marco 1a roda sem voz; o 1b mede latência e VRAM com o modelo já escolhido.
- 📌 Os ADRs 0001, 0004 e 0006 já usam a numeração nova de fases.
