# ADR-0001 · Python como linguagem principal

- **Status:** Aceito
- **Data:** 2026-10-30

## Contexto

O SHIRO depende pesadamente de bibliotecas de áudio e IA que rodam localmente: transcrição (faster-whisper), detecção de voz (Silero VAD), palavra de ativação (openWakeWord), síntese de voz (Piper) e os SDKs dos provedores de LLM. Também precisa conversar com APIs do Windows (áudio, janelas, processos, notificações).

Minha stack mais forte hoje é Node.js/TypeScript, com experiência também em Go.

## Decisão

Usar **Python 3.12** em todo o processo do SHIRO. O painel da Fase 4 pode usar React, porque fica fora do processo e conversa por HTTP/WebSocket.

## Alternativas consideradas

| Alternativa | Por que não |
|---|---|
| TypeScript/Node | Voz e IA local exigiriam processos auxiliares em Python de qualquer jeito, criando dois runtimes e IPC no caminho crítico de latência |
| Go no núcleo + Python para voz/IA | Bom desempenho e tipagem, mas a fronteira entre linguagens fica bem no meio do fluxo de voz. Complexidade alta demais para um projeto pessoal |
| C#/.NET | Ótimo acesso ao Windows, mas ecossistema de IA local muito menor |

## Consequências

- ✅ Acesso direto a todo o ecossistema de áudio e IA, sem IPC.
- ✅ SDKs oficiais de todos os provedores de LLM.
- ⚠️ O GIL limita paralelismo em Python puro. Mitigação: a inferência pesada acontece em código nativo que libera o GIL, rodando em threads (ver arquitetura, seção 10).
- ⚠️ Empacotar Python no Windows é mais chato. Mitigação: `uv` com lockfile e script de instalação.
- ⚠️ Tipagem é opcional em Python. Mitigação: `pyright --strict` no núcleo, obrigatório na CI.
- 📌 Python 3.12 em vez de versões mais novas, porque bibliotecas de áudio e ML costumam demorar a publicar wheels. Reavaliar uma vez por ano.
