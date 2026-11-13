# ADR-0024 · Controle do PC: sites, teclado, leitura da tela e cliques

- **Status:** Aceito
- **Data:** 2026-11-13
- **Complementa:** [ADR-0005](0005-ferramentas-com-politica-de-risco.md), [ADR-0021](0021-comandos-conhecidos-e-captura-do-microfone.md)

## Contexto

A SHIRO só abria e fechava apps da lista. Ela não conseguia abrir um site, pesquisar no YouTube, digitar ou clicar num botão, e o modelo respondia que "não consegue". Controlar o PC é o motivo principal do projeto.

## Decisão

Cinco ferramentas no grupo `control`. Elas só aparecem para o modelo quando o pedido fala de site, tecla, clique, tela etc. (`TOOL_GATES`).

| Ferramenta | O que faz | Risco |
|---|---|---|
| `open_url` | abre um endereço (só http/https) ou uma busca no Google, YouTube, Wikipedia, GitHub ou Maps, no navegador padrão ou num escolhido | R1, `external` |
| `type_text` | digita o texto na janela em uso (`SendInput` com `KEYEVENTF_UNICODE`, então acentos funcionam) | R2 |
| `press_keys` | tecla ou atalho (`ctrl+l`, `alt+tab`, `win+d`); a combinação é validada antes | R2 |
| `read_screen` | lista botões, links, abas e campos da janela em uso pelo nome (UI Automation) | R0, saída não confiável |
| `click_on` | acha o elemento pelo nome (igual > começa com > contém > parecido; botão antes de link) e clica no centro dele | R2 |

- **Janela em uso:** é a da frente. Quando é a própria SHIRO (o usuário clicou no microfone do programa), vale a próxima janela visível. Antes de digitar ou clicar, essa janela volta para a frente.
- **Segurança:** o que vem de `read_screen` é conteúdo externo. Depois dele, digitar, apertar teclas e clicar pedem confirmação, porque o texto de uma página não pode mandar a SHIRO agir (política existente, ADR-0005). Com `read_only_mode`, tudo acima de R0 confirma. `[policy] pc_control = false` desliga as cinco ferramentas.
- **Tier 0 dos sites:** "abre o YouTube" e "pesquisa X no YouTube" viram `open_url` sem passar pelo modelo (`SiteRules`). Os nomes são comparados pela pronúncia, então "iutubi" também vale. Apps da lista têm prioridade sobre sites.
- **Voz:** os nomes dos sites entram nas hotwords e no prompt do Whisper. As frases "Abra o YouTube." entram no catálogo da correção de comandos (ADR-0021). `[voice.stt] extra_words` acrescenta os termos do próprio usuário.

## Alternativas consideradas

| Alternativa | Por que não |
|---|---|
| Clicar por coordenadas vindas de um print + modelo de visão | O modelo local não enxerga; mandar prints para a nuvem expõe a tela inteira |
| pyautogui | Só coordenadas e teclas; não sabe o nome dos botões |
| Automação do navegador (Playwright/CDP) | Exige abrir o navegador em modo de depuração; não serve para apps do Windows |

## Consequências

- Pedidos como "abre o Chrome e pesquisa X na Wikipedia", "digita oi e aperta Enter" e "clica em Entrar" passam a funcionar.
- Elementos sem nome acessível (jogos, canvas) não são clicáveis pelo nome.
- A leitura da tela é limitada a 2.500 nós e 6 s, para páginas grandes não travarem o turno.
