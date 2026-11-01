# ADR-0017 · Memória de longo prazo local

- **Status:** Aceito
- **Data:** 2026-11-01
- **Requisitos:** RF-41 a RF-44 · substitui a ideia de embeddings pelo Ollama (`nomic-embed-text`)

## Contexto

A memória guarda o que o usuário pede ("lembra que eu torço pro Coritiba") e usa esses fatos quando ajudam a responder ("qual é o meu time?"). O modelo de dados (`docs/04-modelo-de-dados.md`) já previa `MEMORY_FACT` e `MEMORY_EMBEDDING` separados, além da lista do que nunca entra: senhas, documentos e dados bancários.

O plano original gerava os vetores pelo Ollama. Só que a GPU de 4 GB está ocupada pelo modelo de linguagem (ADR-0010), e trocar de modelo a cada pedido custaria segundos.

Comparação no PC de referência (CPU, int8): 8 fatos, 10 perguntas que combinam com um deles e 8 que não combinam com nenhum.

| Modelo (ONNX int8) | Tamanho | Acertou o fato certo | Melhor limiar decide certo | Tempo |
|---|---:|---:|---:|---:|
| multilingual-e5-small | 113 MB | 7/10 | 14/18 | 4 ms |
| **paraphrase-multilingual-MiniLM-L12-v2** | **113 MB** | **10/10** | **15/18** | **3 ms** |
| multilingual-e5-base | 265 MB | 9/10 | 14/18 | 12 ms |
| paraphrase-multilingual-mpnet-base-v2 | 265 MB | 10/10 | 16/18 | 11 ms |

Os modelos e5 comprimem as notas numa faixa estreita: perguntas sem relação com nenhum fato ficaram entre 0,84 e 0,90. Isso torna um limiar fixo inútil.

## Decisão

1. **Vetores na CPU com `paraphrase-multilingual-MiniLM-L12-v2` em ONNX int8** (113 MB, Apache-2.0). O modelo roda pelo onnxruntime e pelo `tokenizers` que a voz já instala, e é baixado por `shiro setup` com os hashes do Hugging Face.
2. **Reserva sem download:** sem o modelo, a busca é por radicais com hash, que acha palavras em comum mas não sinônimos. Trocar de modelo recalcula os vetores na primeira busca.
3. **Só entra o que foi pedido**, e o pedido passa por um filtro:
   - senha, token, chave de API, CPF/RG, cartão ou conta bancária são recusados;
   - sequências longas de números e textos com cara de segredo também.
4. **Tier 0:** "lembra que X", "esquece X", "esquece tudo" (R2, pede confirmação) e "o que você sabe sobre mim?". "Lembra que tenho prova amanhã" tem prazo, então fica com as atividades.
5. **No contexto do modelo local:**
   - até 3 memórias com nota ≥ 0,43 entram como mensagem de sistema **logo antes da fala**. A persona não muda e o cache de prefixo do Ollama continua valendo (ADR-0011);
   - um turno com memórias no contexto vira `local_only` e **nunca sobe para a nuvem**;
   - com Tier 2 pedido explicitamente, as memórias não entram.
6. **Esquecer exige semelhança e pelo menos uma palavra em comum**, porque apagar é definitivo. Se duas memórias empatam, a SHIRO pergunta qual.
7. **Busca por força bruta com numpy:** com centenas de fatos ela leva microssegundos. O `sqlite-vec` fica para quando houver dezenas de milhares.

## Alternativas consideradas

| Alternativa | Por que não |
|---|---|
| Embeddings pelo Ollama | Disputa a GPU com o modelo de linguagem; trocar de modelo custa segundos |
| multilingual-e5 (small/base) | Notas comprimidas; errou o fato em 1 a 3 de 10 perguntas |
| paraphrase-multilingual-mpnet-base-v2 | Só um pouco melhor, com 2,4× o tamanho |
| `sqlite-vec` | Dependência nativa sem ganho na escala de uma pessoa |
| Deixar o modelo decidir o que lembrar | Inferências sobre o usuário ficam de fora por princípio (docs/04, seção 3) |

## Consequências

- "Qual é o meu time?" acha "eu torço pro Coritiba" sem palavra em comum.
- Cerca de 3 em 18 pedidos podem trazer uma memória que não ajuda. O modelo é instruído a ignorá-la, e o custo é deixar aquele turno local.
- Para usar outro modelo, mude `memory.embedding_model`. Os limiares dos modelos medidos ficam numa tabela no código.
