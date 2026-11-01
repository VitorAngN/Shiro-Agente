# Avaliação do agente completo · 2026-11-01

Avaliação de ponta a ponta com `evals/run_agent.py`: cada fala passa pelo `AgentLoop` real (Tier 0, modelo local, política e ferramentas), com o PC simulado, clima fixo, confirmações automáticas e relógio fixo (quarta-feira, 10h).

- **Modelo:** `qwen3:4b-instruct` no Ollama, `num_ctx` 4096, todas as camadas na GPU (ADR-0010, ADR-0011)
- **Máquina:** GTX 1650 4 GB, i5-10300H, 24 GB de RAM, Windows 11
- **Nuvem:** desligada (só Tier 0 e Tier 1)

## Evolução

| Rodada | Casos | Ferramenta certa | Argumentos certos | O que mudou |
|---|---:|---:|---:|---|
| 1 | 21 | 81% | 67% | Primeira rodada com atividades |
| 2 | 21 | 86% | 76% | Schema das ferramentas voltou a ter o campo `title`; persona e descrições mais claras |
| 3 | 27 | 96% | 89% | Prazos ancorados na fala e Tier 0 de atividades (ADR-0014); prazos comparados pelo momento resultante |
| 4 | 28 | 96% | 96% | Dia e hora separados na frase; "X já era"; busca ignora demonstrativos |
| 5 | 29 | **100%** | **100%** | "risca X", "dá baixa em X"; descrição de `complete_activity` |

Na rodada 4 o único erro foi o mais grave: o modelo respondeu "Chamei a ferramenta para marcar a prova de física como concluída" sem ter chamado nada, e a frase chegou ao usuário. A checagem de ação alegada (ADR-0011) passou a reconhecer esse padrão e promessas como "vou marcar"; desde então, uma resposta assim vira "Não consegui executar isso, e nenhuma ação foi feita."

## Distribuição e latência (rodada 5)

- **Tier 0:** 18 de 29 casos, em cerca de 10 ms, sem modelo.
- **Tier 1:** 11 casos. Resposta sem ferramenta entre 0,4 e 1,3 s; com ferramenta (duas chamadas ao modelo) cerca de 2 s.
- **Primeira chamada após o aquecimento:** 1,3 s. Antes da correção do schema ela levava 8,5 s.
- **Pedido completo:** cerca de 2.000 tokens (persona e 14 ferramentas).

## Limites desta avaliação

- 29 casos escritos à mão. Os casos do Tier 0 medem a gramática; só os 11 do Tier 1 medem o modelo.
- O texto chega já transcrito. Erros de reconhecimento de voz entram na avaliação do marco 1b.
- Só verifica a escolha da ferramenta e dos argumentos. A qualidade da resposta falada não é pontuada.
- Com temperatura 0 a variação entre rodadas é pequena, mas existe. Antes de concluir algo, rode de novo.

## Como reproduzir

```powershell
uv run python -m evals.run_agent --out evals/results/ultima.json
uv run python -m evals.run_agent --only atv rem clm   # só atividades e lembretes
```
