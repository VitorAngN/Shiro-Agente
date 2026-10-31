# ADR-0006 · Home Assistant via MCP para a casa

- **Status:** Proposto (Fase 5)
- **Data:** 2026-10-30

## Contexto

Ainda não há dispositivos inteligentes em casa. A automação residencial entra na Fase 5, mas a arquitetura precisa estar pronta para ela sem retrabalho. Integrar cada fabricante diretamente no SHIRO (Tuya, Philips, Xiaomi…) seria reinventar o que o Home Assistant já faz para milhares de dispositivos.

## Decisão

1. **Home Assistant** é a fonte da verdade sobre dispositivos, estados e automações da casa.
2. O SHIRO conversa com ele por **MCP**: o Home Assistant expõe um servidor MCP (pela integração própria de servidor MCP ou pelo servidor comunitário `ha-mcp`), e a ponte MCP do SHIRO transforma essas ferramentas em `Tool`s normais, sujeitas ao motor de políticas.
3. O Home Assistant roda em uma **máquina sempre ligada** (Raspberry Pi ou mini PC), não no PC principal. Assim a casa continua funcionando com o PC desligado.
4. Ao comprar dispositivos, dar preferência a **controle local** (Zigbee, Matter, ESPHome) em vez de dispositivos que só funcionam pela nuvem do fabricante.
5. Mapeamento de risco por domínio: luzes e mídia R1, clima R1, tomadas R2, fechaduras, alarmes e portões R3.

## Alternativas consideradas

| Alternativa | Por que não |
|---|---|
| Integrar fabricantes direto no SHIRO | Trabalho enorme, frágil e redundante com o Home Assistant |
| Adaptador próprio para a API REST/WebSocket do Home Assistant | Funciona, mas o MCP generaliza: a mesma ponte serve para qualquer outro servidor MCP no futuro |
| Home Assistant em Docker no PC principal | A casa pararia sempre que o PC estivesse desligado ou reiniciando |
| Assistentes comerciais (Alexa, Google Home) como ponte | Dependência de nuvem e controle limitado |

## Consequências

- ✅ Milhares de dispositivos suportados sem código novo no SHIRO.
- ✅ Automações críticas (ex.: luz do corredor à noite) rodam no Home Assistant, independentes do SHIRO.
- ⚠️ Mais uma máquina para manter.
- ⚠️ Servidores MCP de terceiros são superfície de ataque. Mitigação: lista de permitidos e ferramentas MCP entrando como R2 até o mapeamento manual (ameaça A-09).
