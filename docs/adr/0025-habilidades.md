# ADR-0025 · Habilidades montadas pela SHIRO

- **Status:** Aceito
- **Data:** 2026-11-13
- **Complementa:** [ADR-0023](0023-aprendizado-por-licoes.md), [ADR-0024](0024-controle-do-pc.md)

## Contexto

O usuário quer pedir "quero que você saiba fazer X" e a SHIRO passar a saber, sem esperar uma versão nova. As lições (ADR-0023) só trocam uma frase por outra. Faltava uma sequência de ações com nome.

## Decisão

- **Habilidade** = nome + passos. Cada passo é uma ferramenta que já existe, com argumentos (`open_program`, `open_url`, `type_text`, `press_keys`, `click_on`, `set_volume`...). A SHIRO **não escreve nem roda código novo**: com teclado e mouse liberados, código gerado na hora seria um risco grande num projeto público.
- O modelo (na nuvem, `[router] cloud_groups`) monta os passos e chama `create_skill`. Antes de pedir aprovação, os passos são validados contra as ferramentas reais. Passo inválido volta como erro para o modelo corrigir, sem incomodar o usuário. Com tudo válido, a confirmação mostra os passos um a um e sempre é pedida (`confirm=True`).
- Para usar, basta falar o nome ("modo estudo", "ativa o modo estudo"). A habilidade roda no Tier 0, sem modelo, e cada passo passa pela política de sempre.
- Nome terminado em `{x}` guarda o resto da frase: "toca no spotify {x}" + "toca no Spotify Matuê" troca `{x}` por "Matuê" nos argumentos.
- Uma habilidade não cria nem apaga habilidades ou lições. Ferramentas R4 nunca viram passo.
- `list_skills` e `forget_skill` completam. Guardadas na tabela `skill` (migração 0006).

## Consequências

- Pedidos novos viram atalhos sem mexer no código. O que nenhuma ferramenta faz continua impossível até existir uma ferramenta para isso.
- Cliques por nome dependem do que a janela expõe ao UI Automation (ADR-0024).
