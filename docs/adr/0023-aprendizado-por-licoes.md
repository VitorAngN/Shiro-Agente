# ADR-0023 · Aprender com o usuário: lições "quando eu disser X, faça Y"

- **Status:** Aceito
- **Data:** 2026-11-12
- **Complementa:** [ADR-0003](0003-roteamento-hibrido-de-llm.md), [ADR-0018](0018-rotinas-arquivos-web.md)

## Contexto

Até aqui, ensinar algo novo à SHIRO exigia editar o `shiro.toml` (apelidos de apps, rotinas). O objetivo é ela aprender aos poucos, por conversa: um apelido que o Whisper erra, um atalho para vários comandos, um nome próprio que só o usuário usa.

## Decisão

Uma **lição** troca uma expressão (até 6 palavras) pelo significado que o usuário deu. A troca acontece no texto do pedido, antes do roteador.

- **Ensinar:** "quando eu disser modo jogo, feche o Discord e abra a Steam", "aprende que stim é steam".
- **Usar:** "modo jogo" vira "feche o discord e abra a steam" e segue o caminho de qualquer pedido. "abra o stim" vira "abra o steam".
- **Esquecer e listar:** "desaprende modo jogo", "o que você aprendeu?".

Pontos de desenho:

1. **A lição não executa nada por conta própria.** Ela só reescreve o pedido. Cada comando resultante passa pelo Tier 0, pela política e pela confirmação, como se o usuário tivesse falado por extenso. Ensinar não é um jeito de pular a política.
2. **Serve também para o modelo.** Se o texto reescrito não for um comando conhecido, ele vai para o modelo já com o significado ("o chefe" vira "o professor de cálculo").
3. **Comandos em sequência.** O roteador passou a aceitar "A e B" e "A e depois B" quando cada parte, sozinha, é um comando do Tier 0. Se uma parte não for, o pedido inteiro vai para o modelo.
4. **Quem ensina fala a expressão crua.** As regras de ensinar e desaprender olham o texto antes da troca.
5. **Limites.** A expressão mais longa ganha da mais curta; o significado não pode conter a própria expressão; no máximo 300 lições.

As lições ficam no SQLite (migração 0005) e em memória, num único padrão de busca compilado a cada mudança.

## Alternativas consideradas

| Alternativa | Por que não |
|---|---|
| Guardar a lista de chamadas de ferramenta | Congela os argumentos e escapa da validação quando as ferramentas mudam; texto é auditável e o usuário entende |
| Deixar o modelo "lembrar" pela memória de longo prazo | Não é determinístico e custa uma chamada ao modelo a cada uso |
| Ajuste fino do modelo | Caro, lento e impossível de desfazer uma lição só |

## Consequências

- A tela "Ensinar" do programa passa a ter de onde ler e onde gravar.
- Uma lição mal escolhida (ensinar "abra" como outra coisa) muda pedidos comuns; listar e desaprender por voz são a saída.
- Próximo passo: as correções da voz (o que ela ouviu contra o que era para ser) virarem sugestões de lição.
