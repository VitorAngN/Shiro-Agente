# ADR-0026 · Escrever por voz: texto pronto e modo ditado

- **Status:** Aceito
- **Data:** 2026-11-13
- **Complementa:** [ADR-0024](0024-controle-do-pc.md)

## Contexto

O usuário quer falar e ver o texto aparecer no programa em uso: código no VS Code, notas formatadas no Obsidian.

## Decisão

- **`write_text`** (R2): o modelo redige o texto final (Markdown para notas, código completo para código) e a ferramenta coloca de uma vez, pela área de transferência (Ctrl+V). Colar evita que o editor refaça a indentação ou feche parênteses sozinho, como acontece digitando tecla a tecla. O que estava na área de transferência é devolvido depois. Com `window`, a janela do programa vem para a frente antes (ou o programa é aberto).
- **Modo ditado** (`start_dictation`, Tier 0 para "modo ditado", "vou ditar"): cada frase falada é escrita como foi dita, sem passar pelo modelo. Pontuação falada vira sinal ("vírgula", "nova linha", "abre parênteses", "dois pontos"...). "Parar ditado" encerra; três escutas seguidas sem fala também. Só começa em pedido feito por voz.

## Consequências

- Código ditado palavra por palavra depende do Whisper, que erra símbolos e nomes. Para código, pedir o que se quer ("escreve uma função que...") funciona melhor que ditar caractere a caractere.
- O texto vai para onde o cursor estiver: a SHIRO não escolhe a linha do arquivo.
