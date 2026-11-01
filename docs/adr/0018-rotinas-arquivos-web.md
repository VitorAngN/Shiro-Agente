# ADR-0018 · Rotinas, arquivos, pesquisa na web e ferramentas por assunto

- **Status:** Aceito
- **Data:** 2026-11-01
- **Requisitos:** RF-24, RF-25, RF-31, RF-32

## Contexto

A Fase 3 acrescenta três famílias de ferramentas: arquivos (7), pesquisa na web (1) e rotinas (1). Com a memória, o pedido ao modelo local passaria de 14 para 26 ferramentas.

Já com 18, a avaliação mostrou o modelo de 4B deixando de criar uma atividade que antes acertava. Ferramentas a mais custam tokens (~2.300 por pedido) e precisão.

Também faltavam dois controles na política:

- uma ação R2 que deve **sempre** confirmar (organizar uma pasta inteira é uma chamada só);
- uma ação que **manda dados para fora** do PC num turno que já tem dados pessoais no contexto.

## Decisão

### Ferramentas por assunto

1. Cada ferramenta tem um `group`. As do grupo `core` vão sempre. As de `memory`, `files` e `web` só entram no pedido quando o texto fala do assunto: palavras-chave em `TOOL_GATES`, sobre o texto normalizado ("arquivo", "pasta", "downloads", "lembra", "esquece", "pesquisa", "internet"…).
2. Um grupo usado nos **dois últimos turnos** continua no pedido, para continuações como "e o outro arquivo?".
3. O aquecimento carrega só o núcleo. Pedidos com outros grupos mudam o prefixo e perdem o cache naquele turno (~0,5 a 1 s a mais), mas só nesses pedidos.

### Arquivos (RF-24, RF-25)

4. As ferramentas só enxergam `policy.allowed_folders`, que por padrão é `~/Downloads`. Todo caminho é resolvido e conferido; `..` e atalhos que saem da pasta são recusados.
5. Nomes de arquivo são **conteúdo externo** (`output_trusted=False`) e `local_only`.
6. "Apagar" vira `trash_file`: o arquivo vai para a lixeira da SHIRO (`<dados>/trash`) e pode ser restaurado por `retention.trash_days` (7) dias. A lixeira vencida é esvaziada na partida.
7. `organize_folder` (R2, `confirm=True`) separa a pasta por tipo. A **própria confirmação mostra o plano** ("mover 34 arquivos: 12 em Imagens, 8 em Documentos…"): esse é o dry-run. Downloads em andamento (`.crdownload`, `.part`) ficam onde estão.

### Rotinas (RF-31)

8. Rotinas ficam em `[routines.<nome>]` no `shiro.toml`, como lista de chamadas de ferramenta. Um pedido ("modo estudo", "ativa a rotina estudo" ou um apelido exato) vira **chamadas do Tier 0**: cada passo passa pela política, e lotes acima de `batch_confirm_threshold` pedem confirmação.
9. **Não existe** ferramenta "rode a rotina". Ela executaria passos por fora da política.
10. Na partida, cada passo é validado contra a ferramenta real. Uma rotina inválida é desligada inteira e aparece em `App.problems`; nunca roda pela metade.

### Pesquisa na web (RF-32)

11. `web_search` usa o Gemini com busca do Google (grounding) e devolve o resumo com as fontes. Ela conta nos mesmos limites por minuto, por dia e de orçamento do Tier 2, e só existe com a chave configurada.
12. A ferramenta é `external`. Num turno com contexto pessoal (memórias, arquivos), a política pede confirmação antes de mandar a pergunta para fora. O resultado é conteúdo externo.

### Política

13. `ToolSpec.confirm`: sempre pede confirmação a partir de R1.
14. `ToolSpec.external` mais contexto privado: pede confirmação mesmo em R0.

## Alternativas consideradas

| Alternativa | Por que não |
|---|---|
| Mandar todas as ferramentas sempre | O 4B errou mais com 18; com 26 pioraria, e cada pedido ficaria ~700 tokens maior |
| Escolher ferramentas com o próprio modelo (duas chamadas) | Dobra a latência de todo pedido |
| Escolher por embeddings | Mais complexo e menos previsível que palavras-chave; fica como evolução |
| Apagar de verdade com confirmação | Um erro de reconhecimento de voz não pode custar um arquivo |
| Ferramenta `run_routine` | Executaria passos sem passar pela política |
| API de busca própria (SerpAPI, Brave) | Mais uma chave e mais um contrato; o Gemini já está configurado |

## Consequências

- Pedidos comuns (volume, apps, atividades, hora) continuam com o núcleo e o cache de prefixo.
- Um pedido de arquivo sem nenhuma das palavras-chave ("cadê aquele boleto?") não vê as ferramentas de arquivo. O modelo responde que não consegue e o usuário reformula. Novas palavras entram em `TOOL_GATES` conforme o uso real mostrar.
- "Organiza meus downloads" sempre mostra o plano e espera um "sim".
