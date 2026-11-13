# ADR-0027 · Visão da tela e esperas

- **Status:** Aceito
- **Data:** 2026-11-13
- **Complementa:** [ADR-0024](0024-controle-do-pc.md)

## Contexto

O UI Automation só acha o que tem nome: botões, links, campos. Linhas de texto num editor, ícones desenhados e jogos não têm. O usuário também quer que a SHIRO espere algo acontecer ("quando aparecer Aceitar no LoL, aceita"; "em 3:00 do vídeo, pausa").

## Decisão

### Visão
- `click_on` tenta primeiro pelo nome. Se não acha, manda o print da janela em uso para o Gemini, que devolve o centro do alvo em milésimos da imagem; a SHIRO converte para pixels da tela e clica.
- `look_at_screen` descreve a janela (o que aparece, em que estado o jogo está).
- O print só sai do PC nesses casos, conta nos limites do Tier 2 e é reduzido para até 1600 px de largura.
- `scroll` (roda do mouse) e `hold_keys` (segurar W para andar). As teclas agora vão com o código físico (scan code), que os jogos leem.

### Esperas (`Waits`)
- `wait_then`: espera um tempo e roda os passos.
- `when_visible`: olha a tela de tempos em tempos (pelo nome primeiro, que é de graça; depois pelo print) e roda os passos quando o alvo aparece. Desiste no prazo e avisa.
- Passos no mesmo formato das habilidades (ADR-0025), validados antes. Rodam com `AgentLoop.run_calls`, pela política de sempre. O resultado vira `BackgroundNotice`: aparece na conversa e é dito em voz alta.
- `list_waits` e `cancel_waits`. No máximo 10 ao mesmo tempo. O print do vigia não traz a janela para a frente.

## Consequências

- Um vigia pela visão gasta um pedido da nuvem a cada olhada (padrão: a cada 6 s). Com 15 pedidos por minuto e 200 por dia, um vigia longo consome a cota: o prazo padrão é 20 minutos.
- O print mostra a janela da frente; um vigia não enxerga uma janela coberta por outra.
