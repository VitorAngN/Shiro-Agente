# Registro de decisões de arquitetura (ADRs)

Cada decisão importante fica registrada aqui, com o contexto e as alternativas da época. ADRs não são editados depois de aceitos. Se uma decisão muda, um ADR novo **substitui** o antigo e os dois apontam um para o outro.

| ADR | Título | Status |
|---|---|---|
| [0001](0001-python-como-linguagem-principal.md) | Python como linguagem principal | Aceito |
| [0002](0002-monolito-modular-hexagonal.md) | Monólito modular com arquitetura hexagonal | Aceito |
| [0003](0003-roteamento-hibrido-de-llm.md) | Roteamento híbrido de LLM com adaptadores próprios | Aceito, em parte substituído pelo 0010 |
| [0004](0004-pipeline-de-voz-local.md) | Pipeline de voz 100% local | Aceito, em parte substituído pelos 0010 e 0012 |
| [0005](0005-ferramentas-com-politica-de-risco.md) | Ferramentas com risco declarado e motor de políticas | Aceito |
| [0006](0006-home-assistant-via-mcp.md) | Home Assistant via MCP para a casa | Proposto |
| [0007](0007-sqlite-para-persistencia.md) | SQLite para persistência | Aceito |
| [0008](0008-processo-de-usuario-no-windows.md) | Processo de usuário iniciado no logon, não serviço do Windows | Aceito |
| [0009](0009-voz-e-atividades-no-mvp.md) | Voz e atividades no MVP | Aceito |
| [0010](0010-hardware-gpu-4gb.md) | Ajustar a arquitetura para GPU de 4 GB | Aceito |
| [0011](0011-ajustes-do-benchmark-local.md) | Ajustes do agente a partir do benchmark local | Aceito |
| [0012](0012-identidade-da-shiro.md) | Identidade da SHIRO: persona, voz e visual | Aceito |
| [0013](0013-localizacao-automatica.md) | Localização automática para o clima | Aceito |
| [0014](0014-prazos-ancorados-na-fala.md) | Prazos ancorados na fala e atividades no Tier 0 | Aceito |
| [0015](0015-implementacao-da-voz.md) | Implementação da voz (marco 1b) | Aceito |
| [0016](0016-sempre-ligado.md) | Sempre ligado: bandeja, "Ei, Shiro" e início com o Windows | Aceito |
| [0017](0017-memoria-local.md) | Memória de longo prazo local | Aceito |
| [0018](0018-rotinas-arquivos-web.md) | Rotinas, arquivos, pesquisa na web e ferramentas por assunto | Aceito |
| [0019](0019-painel-local.md) | Painel local: API no loopback e página sem build | Aceito |
| [0020](0020-camadas-e-estruturas-de-dados.md) | Árvore em camadas e estruturas de dados próprias | Aceito |
| [0021](0021-comandos-conhecidos-e-captura-do-microfone.md) | Comandos conhecidos na voz e captura sem os efeitos do Windows | Aceito |
| [0022](0022-motor-como-servico-e-aparelhos.md) | Motor como serviço; programa e celular como clientes pareados | Aceito |
| [0023](0023-aprendizado-por-licoes.md) | Aprender com o usuário: lições "quando eu disser X, faça Y" | Aceito |
| [0024](0024-controle-do-pc.md) | Controle do PC: sites, teclado, leitura da tela e cliques | Aceito |
| [0025](0025-habilidades.md) | Habilidades montadas pela SHIRO a partir das ferramentas | Aceito |

## Modelo

```markdown
# ADR-NNNN · Título curto no imperativo

- **Status:** Proposto | Aceito | Substituído por ADR-XXXX | Descontinuado
- **Data:** AAAA-MM-DD

## Contexto
Qual problema ou força motivou a decisão. Fatos, restrições, números.

## Decisão
O que foi decidido, em uma ou duas frases afirmativas.

## Alternativas consideradas
Cada alternativa com o motivo de não ter sido escolhida.

## Consequências
O que melhora, o que piora e o que passa a ser obrigatório.
```
