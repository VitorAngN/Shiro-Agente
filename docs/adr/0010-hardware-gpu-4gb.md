# ADR-0010 · Ajustar a arquitetura para GPU de 4 GB

- **Status:** Aceito
- **Data:** 2026-10-31
- **Substitui em parte:** [ADR-0003](0003-roteamento-hibrido-de-llm.md) (contexto de hardware e candidatos a modelo local) e [ADR-0004](0004-pipeline-de-voz-local.md) (onde o STT roda)

## Contexto

Os ADRs 0003 e 0004 partiram da premissa de uma GPU com 8 GB de VRAM. A verificação no hardware real (`nvidia-smi`) mostrou uma **GTX 1650 com 4 GB**.

O [benchmark de 2026-10-31](../benchmarks/2026-10-31-modelo-local.md) mediu:

| Modelo | Divisão CPU/GPU | Geração | Resposta de ~30 tokens |
|---|---|---|---|
| `qwen3:8b` | 61% / 39% | 5,0 tokens/s | ~6 s |
| `qwen3:4b-instruct` | esperado 100% GPU | 17,6 tokens/s | ~1,7 s |

Um modelo de 8B não cabe na placa e fica lento demais para voz. Fatores a favor: a tela não usa a placa NVIDIA, então os 4 GB ficam livres para o SHIRO.

## Decisão

### 1. Modelo local na faixa de 3–4B

- **Padrão provisório:** `qwen3:4b-instruct` (2,5 GB, sem modo de pensamento, com suporte a ferramentas).
- **Candidatos para o benchmark do marco 1a:** `qwen3:4b-instruct`, `phi4-mini` (3,8B) e `llama3.2:3b`. O vencedor é decidido pela suíte de avaliação em pt-BR, como previsto no ADR-0003.
- Modelos que não cabem inteiros na GPU ficam fora do Tier 1.

### 2. Contexto de 4096 tokens

Pesos de ~2,5 GB mais um contexto de 8K tokens (~1,1 GB estimados para o cache do modelo de 4B) deixariam a placa no limite. O padrão passa a ser **4096 tokens**. O prompt do SHIRO (persona + ferramentas) precisa caber em ~1,5 mil tokens, e o histórico é resumido antes de estourar. Cache de contexto quantizado (`OLLAMA_KV_CACHE_TYPE=q8_0`) será testado no marco 1a como forma de ganhar espaço.

### 3. Transcrição de voz (STT) na CPU

A GPU fica inteira para o modelo de linguagem. O faster-whisper roda na **CPU em int8**. O spike do marco 1b compara os modelos `base` e `small` em pt-BR quanto a precisão e latência, considerando o processador da máquina.

### 4. Mais peso no Tier 0 e no Tier 2

- **Tier 0** (regras, sem LLM) passa a cobrir o máximo possível dos comandos frequentes, porque é o caminho mais rápido.
- **Tier 2** (nuvem) passa a ser o caminho esperado para tarefas de várias etapas. O escalonamento automático do ADR-0003 já cobre isso.

## Alternativas consideradas

| Alternativa | Por que não |
|---|---|
| Manter o 8B com parte na CPU | 5 tokens/s inviabiliza a conversa por voz |
| Tudo na nuvem | Contraria o local-first: sem internet, nada funciona, e todo pedido sai do PC |
| Modelo de 1–2B | Cabe com folga, mas a qualidade de chamada de ferramentas em pt-BR tende a cair muito. Fica como plano B se os de 3–4B não atingirem a latência |
| STT na GPU junto com o LLM | Não sobra VRAM com o modelo de 4B carregado |
| Trocar de placa de vídeo | Fora do escopo do projeto. A arquitetura continua pronta para isso: com mais VRAM, basta mudar a configuração |

## Consequências

- ✅ Respostas locais ~3,5× mais rápidas que com o 8B.
- ✅ Nenhuma mudança estrutural: modelo, contexto e dispositivo do STT são configuração.
- ⚠️ Modelos de 3–4B erram mais em ferramentas e datas. Mitigação: Tier 0 mais amplo, datas resolvidas por código (ADR-0009), validação com escalonamento para a nuvem.
- ⚠️ A meta de 2,5 s do Tier 1 (RNF-01) fica apertada: a estimativa atual vai de 2,0 a 3,3 s. O marco 1a mede o caminho completo e, se preciso, a meta é revista com dados.
- ⚠️ Mais pedidos vão para a nuvem, o que aumenta a importância do orçamento diário e do rate limiter.
- 📌 Fechar apps que usam a placa (jogos, overlays, navegador com aceleração de hardware) libera VRAM. O Modo Desempenho (RF-26) faz o contrário: descarrega o modelo quando a placa for necessária para outra coisa.
