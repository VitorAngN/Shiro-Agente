# ADR-0019 · Painel local: API no loopback e página sem build

- **Status:** Aceito
- **Data:** 2026-11-01
- **Requisitos:** RF-63, RNF-09, RNF-14; ameaça A-05

## Contexto

A Fase 4 precisa responder, sem abrir o banco na mão, perguntas como "por que esse turno demorou?", "por que ela negou aquilo?" e "o que ela sabe de mim?". Os dados já existem no SQLite: mensagens com camada e latência, chamadas de ferramenta com a decisão da política, auditoria encadeada, uso da nuvem, atividades e memórias.

O roadmap previa FastAPI e React. Três restrições pesam:

- **Local-first:** a página não pode depender da internet (fontes, CDN) nem mandar nada para fora.
- **Serviço local é alvo:** qualquer site aberto no navegador pode tentar falar com `127.0.0.1` (CSRF, DNS rebinding) e outro programa do PC pode tentar a porta (ameaça A-05).
- **Projeto de uma pessoa:** um segundo toolchain (Node, npm, bundler) dobra a manutenção e a cadeia de suprimentos (A-08).

## Decisão

### Servidor

1. FastAPI rodando **no mesmo processo e no mesmo laço do asyncio** da SHIRO (uvicorn como tarefa). É o que permite eventos ao vivo: o painel assina o `EventBus` e repassa `TurnStarted`, `ToolCallCompleted` e `TurnFinished` por WebSocket.
2. Liga sob demanda: "Abrir painel" na bandeja ou `shiro dashboard`. Com `[api] enabled = true`, liga junto com a bandeja (sem abrir o navegador).
3. Escuta só no loopback (`[api] host`: `127.0.0.1`, `::1` ou `localhost`; a configuração recusa outros). A SHIRO abre o socket antes do uvicorn: porta ocupada vira uma mensagem, não o encerramento do processo. No Windows, `SO_EXCLUSIVEADDRUSE` impede outro programa de tomar a porta.
4. Consultas somente leitura sobre as tabelas existentes. A única escrita é apagar uma memória, que passa pelo `MemoryService`.

### Acesso

5. Um token aleatório por execução. O navegador entra por um **link de uso único** (`/login?code=…`) gerado na hora. O código vira um cookie `HttpOnly` e `SameSite=Strict`, e a página nunca vê o token. Scripts locais podem usar `Authorization: Bearer`.
6. `Host` diferente de `127.0.0.1`, `localhost` ou `[::1]` com a porta configurada recebe 400 (DNS rebinding).
7. `DELETE` exige o cabeçalho `X-Shiro: 1`. Um site de fora não consegue mandá-lo sem uma pré-verificação CORS, e o servidor não libera CORS.
8. O WebSocket confere a `Origin` e o cookie antes de aceitar. Uma aba lenta guarda no máximo 100 eventos.
9. Cabeçalhos em toda resposta: CSP `default-src 'none'` com script, estilo, fonte e imagem só da própria origem, nada inline; `frame-ancestors 'none'`; `Referrer-Policy: no-referrer` (o link de entrada leva o código na URL); `Cache-Control: no-store`.

### Página

10. HTML, CSS e JavaScript sem framework e sem build, servidos de `shiro/interfaces/api/static`. Todo dado do banco entra como texto (`textContent`), nunca como HTML: respostas, memórias e resultados de ferramentas podem conter qualquer coisa (A-01).
11. A identidade do [ADR-0012](0012-identidade-da-shiro.md): paleta grafite, ciano para "sistema ok", âmbar só para confirmação e para o que foi barrado, vermelho só na identidade. Os estados mudam de forma além da cor (tracejado para negado e para nuvem, anel tracejado enquanto ela pensa).
12. Fontes Chakra Petch, JetBrains Mono e Noto Sans JP (só 白シロ), em subconjuntos woff2 dentro do pacote (~80 KB, licença OFL junto). Nada vem da internet.

### Seções

13. **Turnos:** pedido, camada, ferramentas com a decisão da política, resposta e tempo, com p50 e p95 por camada e o total de ações barradas. **Atividades** pendentes com as atrasadas marcadas. **Memória** com "Esquecer" em dois cliques. **Rotinas** com apelidos e passos. **Auditoria** com a verificação da cadeia. **Custos** da nuvem por dia e modelo.

## Alternativas consideradas

| Alternativa | Por que não |
|---|---|
| React (o plano original) | Node, npm e bundler para seis telas de leitura; mais dependências para auditar (A-08) e um build para manter |
| Servidor em processo separado | Perderia os eventos ao vivo, ou exigiria uma fila entre processos |
| Token fixo no `shiro.toml` | Fica em arquivo de texto e não expira; o token por execução some quando a SHIRO fecha |
| Token na URL ou no `localStorage` | Vaza por histórico, `Referer` e qualquer script injetado; o cookie `HttpOnly` não é legível pela página |
| Fontes do Google Fonts | Exigiria internet e avisaria um terceiro toda vez que o painel abre |
| Escutar em `0.0.0.0` para ver do celular | Expõe o assistente à rede (A-05). Acesso remoto, se vier, será por túnel autenticado |

## Consequências

- Diagnosticar um turno lento ou uma ação negada é abrir "Turnos": a camada, o tempo e a decisão estão na mesma linha.
- O painel só existe enquanto a SHIRO roda. `shiro dashboard` sozinho mostra o histórico, mas os eventos ao vivo só aparecem quando ele roda junto da bandeja.
- Cada abertura gera um link novo. Um link antigo, ou o painel depois de reiniciar a SHIRO, mostra "Abra pelo link da SHIRO".
- Telas novas são JavaScript simples. Se a interface crescer a ponto de precisar de componentes, a decisão de não ter build será revista.
