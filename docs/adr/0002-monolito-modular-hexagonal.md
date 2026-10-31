# ADR-0002 · Monólito modular com arquitetura hexagonal

- **Status:** Aceito
- **Data:** 2026-10-30

## Contexto

O SHIRO tem muitas partes (voz, agente, ferramentas, memória, agendador, interfaces), roda em uma máquina só e atende um único usuário. A latência entre as partes importa, porque cada milissegundo pesa na resposta por voz. Ao mesmo tempo, quero conseguir trocar peças (modelo, motor de voz, banco) e testar o núcleo sem Windows, sem GPU e sem internet.

## Decisão

- **Um único processo Python** organizado em módulos com fronteiras claras.
- **Portas e adaptadores:** o núcleo (`core`, `policy`) define interfaces com `typing.Protocol` e não importa nenhuma implementação concreta. Adaptadores implementam as portas, e a ligação acontece só na composition root (`app.py`).
- **Barramento de eventos interno** assíncrono para comunicação que não precisa de resposta imediata (estado da bandeja, auditoria, métricas).
- A regra de dependência é verificada automaticamente na CI com `import-linter`.

## Alternativas consideradas

| Alternativa | Por que não |
|---|---|
| Microsserviços (voz, agente e ferramentas separados) | Latência de rede, orquestração e deploy complexos sem nenhum ganho para um usuário em uma máquina |
| Script único sem camadas | Rápido no início, mas impossível de testar sem hardware e difícil de evoluir |
| Framework de agentes como espinha dorsal (LangGraph etc.) | Ver ADR-0003: o loop do agente e a política são o coração do projeto e precisam de controle total |

## Consequências

- ✅ Núcleo testável com fakes, em Linux, na CI.
- ✅ Trocar Ollama, Piper ou SQLite não toca no núcleo.
- ✅ Se um dia algo precisar virar processo separado (ex.: plugins isolados), a porta já existe.
- ⚠️ Mais arquivos e indireção do que um script. Aceitável pelo ganho em testabilidade.
- ⚠️ Uma falha grave pode derrubar o processo inteiro. Mitigação: supervisor que reinicia componentes e início automático pelo Agendador de Tarefas.
