# Benchmark · modelo local em GPU de 4 GB

| Campo | Valor |
|---|---|
| Data | 2026-10-31 |
| Objetivo | Verificar se um modelo de 8B é viável no hardware real, comparar com um de 4B e medir o 4B no formato de pedido do SHIRO |
| Decisões resultantes | [ADR-0010](../adr/0010-hardware-gpu-4gb.md) e [ADR-0011](../adr/0011-ajustes-do-benchmark-local.md) |
| Como reproduzir | `python evals/bench_ollama.py --model qwen3:4b-instruct --num-gpu 99` |

## Ambiente

| Item | Valor |
|---|---|
| Máquina | Notebook com Windows 11 |
| GPU | NVIDIA GeForce GTX 1650, **4 GB** de VRAM, driver 621.01 (CUDA 13.5) |
| Uso da tela | A tela usa a GPU integrada (Intel UHD); a NVIDIA fica livre (`Disp.A Off`) |
| CPU | Intel Core i5-10300H, 4 núcleos / 8 threads |
| RAM | 24 GB |
| Ollama | 0.40.13 |

## Rodada 1 · 8B contra 4B com pedido curto

Mesmo pedido nos dois modelos, com `ollama run <modelo> --verbose`: *"Responda em uma frase: o que é um assistente pessoal?"*.

| Métrica | `qwen3:8b` (`--think=false`) | `qwen3:4b-instruct` |
|---|---|---|
| Tamanho em disco | 5,2 GB | 2,5 GB |
| Divisão CPU / GPU | **61% / 39%** | não medido nesta rodada |
| Velocidade de geração | **5,0 tokens/s** | **17,6 tokens/s** |
| Duração total | 9,9 s | 3,9 s (sem a carga de 6,6 s) |

O 8B não cabe na placa e fica lento demais para voz. Resultado: [ADR-0010](../adr/0010-hardware-gpu-4gb.md).

## Rodada 2 · 4B no formato do SHIRO

O script [`evals/bench_ollama.py`](../../evals/bench_ollama.py) envia cada comando do [conjunto de avaliação](../../evals/datasets/comandos_ptbr.jsonl) (16 casos em pt-BR) com uma persona e **13 ferramentas** no formato do SHIRO. Isso dá **~1,4 mil tokens** de pedido, contexto de 4096 tokens e temperatura 0.

| Métrica | Ollama decide a GPU | `num_gpu = 99` (tudo na GPU) |
|---|---|---|
| Memória do modelo | 3,29 GB | 2,96 GB |
| Divisão CPU / GPU | 34% / 66% | **100% GPU** |
| VRAM usada na placa | 2,3 de 4 GB | 3,1 de 4 GB |
| Velocidade de geração (mediana) | 13,0 tokens/s | **45,4 tokens/s** |
| Latência por comando, p50 | 2,12 s | **0,63 s** |
| Latência por comando, máxima | 3,93 s | **1,13 s** |
| Ferramenta e argumentos certos | 15/16 (94%) | 15/16 (94%) |
| Leitura do pedido completo, sem cache | 138 tokens/s | 152 tokens/s |

### Resultado por caso (`num_gpu = 99`)

| Caso | Pedido | Resultado |
|---|---|---|
| vol-01 | abaixa o volume pra 20 | ✓ `set_volume(level=20)` |
| vol-02 | tá muito alto, diminui um pouco | ✓ `change_volume(delta=-10)` |
| app-01 | abre o spotify | ✓ `open_app(app=spotify)` |
| app-02 | abre o vs code e o discord | ✓ duas chamadas `open_app` |
| sys-01 | quanto de memória ram eu tô usando? | ✓ `system_info(metric=ram)` |
| mid-01 | pula essa música | ✓ `media_control(action=next)` |
| rem-01 | me lembra de entregar o relatório de física às oito da noite | ✓ `create_reminder(at_local=20:00)` |
| neg-01 | apaga a pasta windows | ✓ recusou |
| amb-01 | fecha ele | ✓ perguntou qual app |
| chat-01 | quanto é quinze por cento de trezentos e quarenta? | ✓ respondeu 51 |
| atv-01 | anota o trabalho de cálculo pra sexta | ✓ `create_activity(due_text="pra sexta")` |
| atv-02 | tenho prova de física dia 12 às 19h | ✓ `create_activity(due_text="dia 12 às 19h")` |
| atv-03 | o que eu tenho essa semana? | ✓ `list_activities(period=this_week)` |
| **atv-04** | **terminei o trabalho de cálculo** | **✗ respondeu "Marquei sua atividade como concluída" sem chamar `complete_activity`** |
| atv-05 | adia a prova de física pra semana que vem | ✓ `postpone_activity(due_text="semana que vem")` |
| atv-06 | anota uma atividade | ✓ pediu título e prazo |

## Achados

1. **O cálculo automático de memória do Ollama é conservador.** Com ~1,7 GB livres na placa, ele deixou 34% do modelo na CPU. Forçando todas as camadas na GPU (`num_gpu = 99`), a geração ficou **3,5× mais rápida**, e ainda sobrou ~1 GB de VRAM.
2. **O modelo afirmou uma ação que não executou** (atv-04). Uma regra explícita na persona ("nunca diga que fez algo sem chamar a ferramenta") **não corrigiu** o erro em uma segunda rodada. A proteção precisa estar no código.
3. **A primeira leitura do pedido completo é lenta**: ~150 tokens/s, cerca de 10 s para persona + ferramentas. A GTX 1650 não tem tensor cores. Nas chamadas seguintes, o prefixo comum fica em cache e só a fala nova é lida, por isso a latência por comando fica abaixo de 1,2 s.
4. **Prazos vêm com preposição** ("pra sexta"). O resolvedor de datas do ADR-0009 precisa ignorar "pra", "para" e "até".

## Pendências

- [ ] Comparar com `phi4-mini` e `llama3.2:3b` no marco 1a, com o conjunto de avaliação ampliado.
- [ ] Testar `OLLAMA_FLASH_ATTENTION=1` e `OLLAMA_KV_CACHE_TYPE=q8_0`, para ver se reduzem memória ou aceleram a leitura do pedido.
- [ ] Ampliar os casos de "ação alegada" (variações de "terminei", "já fiz", "pode marcar").
