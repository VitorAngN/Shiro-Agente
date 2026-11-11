# ADR-0022 · Motor como serviço, programa e celular como clientes

- **Status:** Aceito (em implementação por etapas)
- **Data:** 2026-11-11
- **Requisitos:** RF-01, RF-02
- **Complementa:** [ADR-0019](0019-painel-local.md)
- **Adia:** a Fase 5 (Home Assistant)

## Contexto

A SHIRO era usada pelo terminal, pela bandeja e por um painel no navegador. O objetivo agora é um programa de verdade no PC e um app no celular, os dois ligados ao mesmo motor, com o celular funcionando também fora de casa.

O motor (modelo local, memória, atividades, ferramentas do Windows) só faz sentido no PC. Os clientes precisam falar com ele sem abrir a máquina para a rede.

## Decisão

### 1. Um motor, vários clientes

O motor em Python continua sendo o único lugar com modelo, banco e ferramentas. Ele roda em segundo plano (bandeja) e expõe a **API dos aparelhos**. O programa do PC e o app Android são clientes em Flutter, com o mesmo código de interface.

### 2. Cada aparelho tem a própria chave

- O programa do PC pede um pareamento e mostra um QR com o endereço e um código de uso único, válido por 2 minutos.
- O aparelho troca o código por uma chave aleatória de 256 bits, só dele (`POST /v1/pair`).
- O banco guarda só o SHA-256 da chave (migração 0004). Quem ler o banco não consegue se passar pelo aparelho.
- Toda chamada traz a chave em `Authorization: Bearer`. Não há cookie nem sessão de navegador.
- Desligar um aparelho invalida a chave na hora. Cinco códigos errados cancelam o pareamento aberto.

### 3. Alcance: loopback ou Tailscale, nunca a rede local

`[devices] host` aceita só `127.0.0.1`/`::1` ou um endereço da faixa do Tailscale (`100.64.0.0/10`). Qualquer outro valor é recusado na leitura da configuração. O Tailscale cifra o tráfego entre os aparelhos e resolve o acesso fora de casa sem abrir porta no roteador.

### 4. Rotas da primeira etapa

| Rota | O que faz |
|---|---|
| `POST /v1/pair` | Troca o código do QR pela chave do aparelho |
| `GET /v1/me` | Dados do aparelho que chamou |
| `GET /v1/devices` | Aparelhos ativos |
| `DELETE /v1/me` | O aparelho se desliga (sair do app) |
| `POST /v1/chat` | Um turno de conversa por texto |

### 5. Próximas etapas

1. Ligar o servidor à bandeja e gerar o QR.
2. Eventos por WebSocket (estado dela, respostas) e confirmação remota: ação no PC pedida de outro aparelho sempre pergunta.
3. Voz pelo celular (envio do áudio para o Whisper do PC).
4. Notificações de lembretes no celular.

Até a etapa 2 existir, pedidos vindos de outro aparelho que precisem de confirmação são negados.

## Alternativas consideradas

| Alternativa | Por que não |
|---|---|
| Programa do PC embutindo o Python (sem API) | O celular precisaria de outro caminho; duas integrações para manter |
| Expor a API na rede local (Wi-Fi) | Qualquer aparelho da rede alcançaria a porta; não funciona fora de casa |
| Servidor intermediário na nuvem | Os dados passariam por terceiros; custo e mais uma coisa para cair |
| Uma chave só para todos os aparelhos | Perder um celular obrigaria a trocar a chave de todos |
| Reaproveitar o token do painel (ADR-0019) | Ele muda a cada execução e depende de cookie de navegador |

## Consequências

- O programa e o celular usam a mesma API; o que um ganha, o outro ganha.
- A ameaça A-05 passa a cobrir uma API alcançável de fora do PC. As mitigações são a faixa de endereços, a chave por aparelho, o código de uso único e a confirmação remota.
- O celular depende do Tailscale instalado nos dois lados.
- O PC precisa estar ligado para o celular funcionar.
