# ADR-0020 · Árvore em camadas e estruturas de dados próprias

- **Status:** Aceito
- **Data:** 2026-11-04
- **Requisitos:** RNF-11, RNF-12, RNF-13, RNF-15
- **Complementa:** [ADR-0002](0002-monolito-modular-hexagonal.md)

## Contexto

O ADR-0002 definiu um monólito hexagonal, e o `import-linter` garantia que o núcleo não importava adaptadores. Depois de quatro fases, a árvore já não mostrava essa arquitetura:

- 13 módulos soltos na raiz de `src/shiro` (`app.py`, `cli.py`, `voice_app.py`, `settings.py`…);
- pacotes por assunto (`voice/`, `memory/`) misturando regra pura e I/O. `voice/vad.py` tinha o endpointer, que é lógica pura, o Silero, que usa ONNX, e a escuta, que orquestra os dois;
- testes com nome de fase (`test_phase2.py`, `test_phase3.py`), sem relação com o código que testam;
- estruturas de dados improvisadas onde uma estrutura clássica resolveria melhor. O agendador consultava o banco a cada 15 s. A memória relia todos os fatos e vetores do SQLite em cada turno. O endpointer copiava a lista de quadros 31 vezes por segundo.

## Decisão

### Camadas

```text
src/shiro/
├── domain/          entidades, valores, regras puras e portas (Protocols)
├── application/     casos de uso: agente, atividades, memória, rotinas, agendador
├── config/          esquema do shiro.toml e pastas do usuário
├── infrastructure/  adaptadores: llm, persistence, embeddings, tools, voice, system
├── bootstrap/       raiz de composição: monta o grafo de objetos
├── interfaces/      entradas: cli, text, voice, tray, api
└── structures/      estruturas de dados genéricas
```

1. **Regra de dependência:** cada camada só importa as de baixo, na ordem `interfaces → bootstrap → infrastructure → application → config → domain → structures`. O contrato `layers` do `import-linter` verifica isso na CI.
2. **Domínio, aplicação e estruturas sem I/O:** um contrato `forbidden` proíbe `aiosqlite`, `httpx`, `onnxruntime`, `sounddevice`, `faster_whisper`, `keyring`, `psutil`, `fastapi`, `starlette` e `uvicorn` nessas camadas. `numpy` e `pydantic` são permitidos, porque calculam sem tocar no mundo.
3. **Adaptadores independentes:** `llm`, `persistence`, `embeddings`, `voice` e `observability` não importam uns aos outros (contrato `independence`).
4. **`config` abaixo da aplicação:** cada adaptador lê a própria seção (`STTSettings`, `TTSSettings`…). Se a configuração ficasse em `bootstrap`, os adaptadores dependeriam da camada de cima.
5. **Arquivos mistos foram divididos pela fronteira de I/O.** `voice/vad.py` virou `domain/voice/endpointing.py`, `application/voice/listening.py` e `infrastructure/voice/silero.py`. `memory/embedding.py` virou a porta e o embedder por radicais, no domínio, mais o ONNX, na infraestrutura. `app.py` virou `bootstrap/app.py`, `bootstrap/tools.py` e `bootstrap/llm.py`.
6. **Testes espelham o código:** `tests/unit/<camada>/<pacote>/test_<módulo>.py`; `tests/integration/` para o que monta o app real (`build_app`) com dublês só nas bordas; e `tests/fakes/` para dublês compartilhados, sem um arquivo de teste importar outro.

### Estruturas de dados

7. `structures/` guarda estruturas genéricas, tipadas e testadas, sem dependência do resto da SHIRO. Cada uma substitui código que já existia e tem a complexidade documentada:

| Estrutura | Onde | O que melhorou |
|---|---|---|
| `PriorityQueue` (heap mínimo, remoção preguiçosa) | `application.scheduler` | O lembrete dispara no segundo certo, e não até 15 s depois |
| `RingBuffer` (circular, capacidade fixa) | `Endpointer`, agente | Pré-roll do áudio sem copiar a lista a cada quadro; grupos dos últimos turnos |
| `SlidingWindow` (fila FIFO de instantes) | `GuardedProvider` | Limite por minuto da nuvem com custo O(1) amortizado e intenção explícita |
| `LRUCache` (tabela hash + lista ligada) | `CachedEmbedder` | Frases repetidas não passam de novo pelo modelo de embedding |
| `KeywordTrie` (casamento mais longo) | `ToolRegistry` | Palavras por assunto como dados, e exceções ("memória RAM") vencem o radical |
| `hashchain` (lista encadeada por hash) | auditoria | Algoritmo testável sem SQLite; a verificação lê de um cursor, sem lista na memória |
| `VectorIndex` (matriz + top-k) | `MemoryService` | Cada turno faz uma busca em memória e um `PRAGMA` em vez de reler tudo do banco |

8. A biblioteca padrão é usada onde ela já é a implementação certa (`heapq`, `OrderedDict`, `deque`). As classes acrescentam o que ela não dá: chave única e remoção no heap, contadores no cache, longest-match na trie.
9. Quem guarda estado em memória confere se o banco mudou por fora. O índice de memórias usa `PRAGMA data_version`: se o painel, em outro processo, apagar um fato, a bandeja relê antes de usar.

## Alternativas consideradas

| Alternativa | Por que não |
|---|---|
| Manter os pacotes por assunto (`voice/`, `memory/`) | Escondem a fronteira de I/O; um arquivo misto não pode ser verificado por contrato |
| Pacotes por funcionalidade (`features/memory/{domain,application,adapters}`) | Mais pastas para o mesmo número de módulos; os adaptadores de voz e LLM servem a várias funcionalidades |
| Escrever heap, cache e lista ligada do zero | Mais código para manter e mais lento que `heapq`/`OrderedDict` em C; não há ganho para o usuário |
| Índice vetorial em banco (`sqlite-vec`) | Dependência nativa a mais para dezenas ou centenas de fatos, quando uma matriz em memória responde em microssegundos |
| Configuração em `bootstrap` | Inverteria a dependência de todos os adaptadores que leem a própria seção |

## Consequências

- A árvore conta a arquitetura: dá para saber se um arquivo faz I/O pela pasta em que ele está.
- Mover código entre camadas passa a ser uma decisão visível, barrada pela CI quando quebra a regra.
- O agendador acorda no horário exato; a conferência no banco a cada 15 s continua para pegar trabalhos de outro processo.
- Os caminhos de módulo mudaram (`shiro.core.agent` → `shiro.application.agent.loop`, por exemplo). Os ADRs antigos citam os caminhos da época.
