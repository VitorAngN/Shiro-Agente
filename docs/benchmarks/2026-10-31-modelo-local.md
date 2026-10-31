# Benchmark · modelo local em GPU de 4 GB

| Campo | Valor |
|---|---|
| Data | 2026-10-31 |
| Objetivo | Verificar se um modelo de 8B é viável no hardware real e comparar com um de 4B |
| Decisão resultante | [ADR-0010](../adr/0010-hardware-gpu-4gb.md) |

## Ambiente

| Item | Valor |
|---|---|
| GPU | NVIDIA GeForce GTX 1650, **4 GB** de VRAM (4096 MiB) |
| Driver | 621.01 (CUDA 13.5) |
| Uso da tela | A tela não usa a placa NVIDIA (`Disp.A Off`); só 2 MiB ocupados em repouso |
| Ollama | Contexto padrão de 4096 tokens |
| Sistema | Windows |

## Método

Mesmo pedido curto nos dois modelos, com `ollama run <modelo> --verbose`:

```text
Responda em uma frase: o que é um assistente pessoal?
```

O `qwen3:8b` rodou com `--think=false`. O `qwen3:4b-instruct` não tem modo de pensamento. A divisão entre CPU e GPU foi lida com `ollama ps`.

## Resultados

| Métrica | `qwen3:8b` | `qwen3:4b-instruct` |
|---|---|---|
| Tamanho em disco | 5,2 GB | 2,5 GB |
| Memória ocupada ao carregar | 6,0 GB | não medido |
| Divisão CPU / GPU | **61% / 39%** | não medido (esperado: 100% GPU) |
| Tempo de carga | já carregado (13 ms) | 6,56 s (primeira carga) |
| Tokens gerados | 48 | 58 |
| **Velocidade de geração** | **5,04 tokens/s** | **17,55 tokens/s** |
| Duração total | 9,93 s | 10,45 s (3,89 s sem a carga) |

As taxas de leitura do pedido (`prompt eval rate`) foram deixadas de fora: com pedidos de 24 e 32 tokens, e quase todo o pedido do 8B vindo do cache, o número não representa o caso real.

## Leitura

- O `qwen3:8b` não cabe nos 4 GB. O Ollama coloca 61% do modelo na CPU, e a geração cai para ~5 tokens/s.
- O `qwen3:4b-instruct` gera **3,5× mais rápido**.
- Uma resposta falada típica tem ~30 tokens: **~6 s** no 8B contra **~1,7 s** no 4B. Só o 4B é compatível com a meta de latência do Tier 1 ([RNF-01](../02-requisitos.md#rnf)).

## Pendências (marco 1a)

- [ ] Confirmar `100% GPU` no `ollama ps` com o 4B carregado e repetir a medição com o modelo já em memória.
- [ ] Medir a leitura do pedido real do SHIRO (persona + ferramentas, ~1–1,5 mil tokens).
- [ ] Rodar a suíte de avaliação em pt-BR com os candidatos de 3–4B ([ADR-0010](../adr/0010-hardware-gpu-4gb.md)).
- [ ] Testar `OLLAMA_FLASH_ATTENTION=1` e `OLLAMA_KV_CACHE_TYPE=q8_0` para reduzir a memória do contexto.
