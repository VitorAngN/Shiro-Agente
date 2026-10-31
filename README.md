# SHIRO

> Assistente pessoal com IA para Windows: voz, automação do PC e atividades com prazo.
> Local-first, modular e seguro por padrão.

[![CI](https://github.com/VitorAngN/Shiro-Agente/actions/workflows/ci.yml/badge.svg)](https://github.com/VitorAngN/Shiro-Agente/actions/workflows/ci.yml)
![Python 3.12](https://img.shields.io/badge/python-3.12-blue)
[![Licença MIT](https://img.shields.io/badge/licen%C3%A7a-MIT-green)](LICENSE)

**Status:** 🧱 Fase 0 · Fundação concluída · próxima: Fase 1 · MVP de voz
**Autor:** Vitor ([@VitorAngN](https://github.com/VitorAngN))

---

## O que é

O SHIRO é um assistente no estilo "Jarvis" que roda no próprio PC. Você aperta um atalho e fala:

- **"Abre o Spotify e coloca o volume em 30"**: ele executa;
- **"Anota o trabalho de cálculo pra sexta"**: ele registra a atividade, repete a data que entendeu e avisa antes do prazo;
- **"O que eu tenho essa semana?"**: ele responde em voz alta.

O modelo de linguagem é só o "cérebro" que escolhe o que fazer. Quem executa são **ferramentas** pequenas, testáveis e com nível de risco declarado. O SHIRO não depende de um único fornecedor de IA: pedidos simples ficam no PC, com um modelo local, e só o que exige mais raciocínio vai para a nuvem.

## Princípios

| Princípio | Na prática |
|---|---|
| **Local-first** | Áudio nunca sai do PC. Comandos do dia a dia e atividades funcionam offline. |
| **Agnóstico de modelo** | Ollama, Gemini, Claude e OpenAI atrás da mesma interface. Trocar é configuração. |
| **Seguro por padrão** | Toda ferramenta tem nível de risco. Ações irreversíveis exigem confirmação física. |
| **Modular** | Arquitetura hexagonal: o núcleo não conhece Windows, Ollama nem SQLite. Verificado na CI. |
| **Observável** | Cada turno do agente gera trilha de auditoria, métricas de latência e custo. |

## Arquitetura em 30 segundos

```mermaid
flowchart LR
    U(["Usuário"]) -->|"voz / texto / atalho"| IN["Interfaces<br/>voz · bandeja · CLI"]
    IN --> CORE["Núcleo<br/>roteador + agente"]
    CORE --> POL{"Motor de<br/>políticas"}
    POL -->|"permitido"| TOOLS["Ferramentas<br/>PC · atividades · web · casa"]
    POL -->|"arriscado"| CONF["Confirmação"]
    CONF --> TOOLS
    CORE <--> LLM["Gateway de LLM<br/>local + nuvem"]
    CORE <--> MEM[("Memória<br/>SQLite")]
    TOOLS --> OUT["Resposta falada<br/>+ notificação"]
```

Detalhes completos em [docs/03-arquitetura.md](docs/03-arquitetura.md).

## Como rodar (Fase 0)

Requisitos: Windows 10/11, Python 3.12+, Git e [uv](https://docs.astral.sh/uv/).

```powershell
git clone https://github.com/VitorAngN/Shiro-Agente.git
cd Shiro-Agente
uv sync
uv run pre-commit install

uv run shiro --version
uv run shiro config path     # mostra onde fica o shiro.toml
uv run shiro config check    # valida a configuração
```

Para personalizar, copie [`config/shiro.example.toml`](config/shiro.example.toml) para o caminho mostrado por `shiro config path`. Sem arquivo, o SHIRO usa padrões seguros.

## Stack

| Camada | Tecnologia |
|---|---|
| Linguagem | Python 3.12, `asyncio` |
| LLM local | Ollama, modelo de 3–4B escolhido por benchmark próprio (provisório: `qwen3:4b-instruct`) |
| LLM nuvem | Gemini, Claude, OpenAI (adaptadores próprios) |
| Fala → texto | faster-whisper na CPU + Silero VAD |
| Texto → fala | Piper (`pt_BR-faber-medium`), como processo separado |
| Palavra de ativação | openWakeWord ("Ei, Shiro") |
| Persistência | SQLite (WAL) + sqlite-vec |
| Casa (futuro) | Home Assistant via MCP |
| Qualidade | uv, ruff, pyright, import-linter, pytest, pre-commit, gitleaks, pip-audit, GitHub Actions |

## Documentação

| Documento | Conteúdo |
|---|---|
| [01 · Visão e escopo](docs/01-visao-e-escopo.md) | Problema, objetivos, não-objetivos, casos de uso |
| [02 · Requisitos](docs/02-requisitos.md) | Requisitos funcionais e não funcionais com metas mensuráveis |
| [03 · Arquitetura](docs/03-arquitetura.md) | Contexto, contêineres, componentes, fluxos, interfaces |
| [04 · Modelo de dados](docs/04-modelo-de-dados.md) | Entidades, relacionamentos e retenção |
| [05 · Segurança](docs/05-seguranca.md) | Níveis de risco, modelo de ameaças, mitigações |
| [06 · Roadmap](docs/06-roadmap.md) | Fases, entregas e critérios de pronto |
| [07 · Desenvolvimento](docs/07-desenvolvimento.md) | Ambiente, convenções, testes e avaliação |
| [ADRs](docs/adr/README.md) | Registro das decisões de arquitetura |
| [Benchmarks](docs/benchmarks/2026-10-31-modelo-local.md) | Medições no hardware real |

## Privacidade

Este repositório é público; os dados de quem usa o SHIRO não são. Configuração real, banco de dados, logs e chaves de API ficam fora da pasta do projeto, e a CI bloqueia commits com segredos. Detalhes em [docs/05-seguranca.md](docs/05-seguranca.md#repositorio-publico).

Encontrou uma vulnerabilidade? Veja [SECURITY.md](SECURITY.md).

## Licença

[MIT](LICENSE). Componentes com licença GPL (como o Piper) são usados como processos separados, sem serem importados ([ADR-0004](docs/adr/0004-pipeline-de-voz-local.md)).
