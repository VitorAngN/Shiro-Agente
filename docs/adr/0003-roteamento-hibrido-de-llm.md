# ADR-0003 · Roteamento híbrido de LLM com adaptadores próprios

- **Status:** Aceito
- **Data:** 2026-10-30

## Contexto

- A GPU tem 8 GB de VRAM: cabe um modelo de 8–9B parâmetros quantizado em 4 bits, sem folga.
- Modelos locais desse tamanho resolvem bem comandos curtos, mas erram mais em tarefas de várias etapas.
- O plano gratuito do Gemini tem limites baixos, na ordem de 5–10 requisições por minuto (os valores atuais ficam no Google AI Studio). Um agente gasta várias requisições por comando.
- Privacidade: dados pessoais não devem sair do PC sem necessidade.

## Decisão

### 1. Três camadas de roteamento

| Tier | Quem responde | Quando |
|---|---|---|
| **T0** | Gramática de regras, sem LLM | Comandos frequentes e previsíveis |
| **T1** | LLM local via Ollama | Padrão para todo o resto |
| **T2** | LLM na nuvem | Por regra (web, raciocínio longo, pedido explícito) ou por escalonamento quando o T1 falha na validação |

O T2 é bloqueado quando o contexto contém dados `local_only`, quando o orçamento diário acabou ou quando o limite de taxa foi atingido. Nesse caso o SHIRO segue no T1 ou pede esclarecimento.

### 2. Adaptadores próprios, finos

Uma porta `LLMProvider` com formato interno de mensagens e chamadas de ferramenta. Um adaptador por provedor (Ollama, Gemini, Anthropic, OpenAI), cada um usando o SDK oficial e convertendo de e para o formato interno.

### 3. Loop do agente próprio

O `AgentLoop` é implementado no projeto, com o `PolicyEngine` chamado antes de toda ferramenta.

### 4. Escolha do modelo local por benchmark próprio

Candidatos iniciais para 8 GB, segundo levantamentos públicos de outubro de 2026: **Qwen3.5-9B**, **Qwen3-8B**, **Ministral 3 8B** (chamada de função nativa) e **Granite 4.2 8B** (chamada de ferramentas testada em vários idiomas). O vencedor é decidido pela suíte de avaliação em pt-BR da Fase 1. Até lá, o padrão provisório é `qwen3:8b`.

O provedor de nuvem padrão no desenvolvimento é o **Gemini** (plano gratuito). Claude e OpenAI ficam configuráveis como alternativas e fallback.

## Alternativas consideradas

| Alternativa | Por que não |
|---|---|
| Só nuvem | Latência maior, custo recorrente, depende de internet, todo pedido sai do PC |
| Só local | Tarefas complexas ficariam ruins com um modelo de 8B |
| LiteLLM como camada de abstração | Resolve a troca de provedores, mas adiciona uma dependência grande no caminho crítico. Com 4 provedores, adaptadores próprios de ~150 linhas cada dão controle total sobre a normalização de ferramentas. Reavaliar se o número de provedores crescer |
| Framework de agentes (LangGraph, pydantic-ai, SDKs de agentes dos fornecedores) | Aceleram o começo, mas o loop do agente e o ponto de interceptação da política são o centro do projeto. Quero controle explícito e entendimento completo. Reavaliar se o loop ficar complexo demais |
| Fine-tuning de modelo próprio | Custo alto e desnecessário: prompt, ferramentas bem descritas e Tier 0 resolvem |

## Consequências

- ✅ Comandos frequentes respondem em milissegundos e funcionam offline.
- ✅ Custo de nuvem previsível, com teto diário.
- ✅ Trocar de modelo ou fornecedor é configuração.
- ⚠️ Manter quatro adaptadores quando as APIs mudam. Mitigação: testes de contrato com respostas gravadas.
- ⚠️ A gramática Tier 0 precisa ser mantida à mão. Mitigação: casos Tier 0 na suíte de avaliação.
- 📌 No plano gratuito, o Google pode usar os dados para melhorar seus produtos. Por isso, só conteúdo sem `local_only` vai para a nuvem. Reavaliar o plano pago se o uso crescer.
