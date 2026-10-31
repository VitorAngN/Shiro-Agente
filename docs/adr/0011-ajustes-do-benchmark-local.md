# ADR-0011 · Ajustes do agente a partir do benchmark local

- **Status:** Aceito
- **Data:** 2026-10-31
- **Relacionado:** [ADR-0005](0005-ferramentas-com-politica-de-risco.md), [ADR-0010](0010-hardware-gpu-4gb.md)

## Contexto

O [benchmark no hardware real](../benchmarks/2026-10-31-modelo-local.md) rodou o `qwen3:4b-instruct` com 16 comandos em pt-BR no formato de pedido do SHIRO (persona + 13 ferramentas, ~1,4 mil tokens). Ele trouxe três achados:

1. Deixando o Ollama decidir, 34% do modelo ficou na CPU, mesmo com VRAM livre: **13 tokens/s** e latência p50 de **2,1 s**. Com todas as camadas na GPU: **45 tokens/s** e **0,63 s**.
2. A primeira leitura do pedido completo leva **~10 s** (~150 tokens/s). Depois disso, o prefixo comum fica em cache.
3. Para "terminei o trabalho de cálculo", o modelo respondeu "Marquei sua atividade como concluída" **sem chamar nenhuma ferramenta**. Uma regra explícita no prompt não corrigiu o erro.

## Decisão

### 1. Modelo local inteiro na GPU

A configuração passa a ter `llm.local.num_gpu`, com padrão **99** (todas as camadas na GPU). Esse valor é enviado ao Ollama em toda chamada. Com `0`, o modelo roda só na CPU.

### 2. Aquecimento do prefixo e permanência na memória

- **Aquecimento:** ao iniciar, e ao sair do Modo Desempenho, o SHIRO envia ao Ollama uma chamada com a persona e as ferramentas, sem fala do usuário. Assim os ~10 s de leitura acontecem antes do primeiro comando.
- A persona e as definições de ferramentas ficam **estáveis e no início do pedido**, sempre na mesma ordem, para o cache do prefixo funcionar. O que muda (memórias, histórico, fala) vem depois.
- `keep_alive` passa de 10 para **30 minutos**. A VRAM continua liberável a qualquer momento pelo Modo Desempenho (RF-26).

### 3. Verificação de ação alegada

Como o modelo pode afirmar ações que não executou, o `AgentLoop` verifica a resposta final antes de enviá-la ao TTS:

- se o texto final **afirma uma ação** (verbos de conclusão no passado, como "marquei", "abri", "criei", "apaguei", "anotei", "adiei", "pronto") e **nenhuma ferramenta com efeito foi executada com sucesso no turno**, a resposta é bloqueada;
- o turno é refeito uma vez, com uma instrução de correção para o modelo;
- se falhar de novo, o pedido escala para o Tier 2 quando permitido. Caso contrário, o SHIRO responde que não conseguiu executar e pergunta como seguir.

A checagem é heurística e fica do lado seguro: um falso positivo custa uma nova tentativa, e um falso negativo é justamente o caso que já acontece hoje. Os casos "terminei X" e "concluí X" também entram na gramática do Tier 0, que chama `complete_activity` sem passar pelo modelo.

## Alternativas consideradas

| Alternativa | Por que não |
|---|---|
| Deixar o Ollama decidir quanto vai para a GPU | 3,5× mais lento neste hardware |
| Manter o modelo sempre carregado (`keep_alive = -1`) | Prende ~3 GB de VRAM o tempo todo, inclusive fora de uso; 30 minutos mais o Modo Desempenho equilibram melhor |
| Corrigir a ação alegada só com prompt | Testado e não funcionou. Contraria o princípio do ADR-0005: o modelo propõe, o código decide |
| Pedir ao modelo uma resposta estruturada indicando se agiu | Ainda depende de o modelo dizer a verdade sobre si mesmo; a checagem precisa usar o registro real de ferramentas executadas |

## Consequências

- ✅ Latência do Tier 1 bem abaixo da meta de 2,5 s (RNF-01) no trecho do LLM.
- ✅ O usuário nunca ouve "pronto" sem que uma ferramenta tenha de fato executado (RF-16).
- ⚠️ Com `num_gpu = 99`, um modelo ou contexto maior que a placa pode cair no uso de memória compartilhada do Windows e ficar lento sem aviso. Mitigação: o `shiro config check` passará a comparar o tamanho do modelo com a VRAM livre.
- ⚠️ A lista de verbos de conclusão precisa ser mantida e testada. Mitigação: casos próprios na suíte de avaliação.
- 📌 O primeiro comando logo após ligar o PC pode esperar o aquecimento terminar (~15 s, incluindo a carga do modelo). A bandeja mostra o estado "preparando".
