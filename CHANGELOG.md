# Changelog

Todas as mudanças relevantes do SHIRO são registradas aqui.
Formato baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/) e versionamento [SemVer](https://semver.org/lang/pt-BR/).

## [Não lançado]

### Alterado
- Arquitetura ajustada para o hardware real, uma GTX 1650 com 4 GB de VRAM (ADR-0010): modelo local de 3–4B (provisório `qwen3:4b-instruct`), contexto de 4096 tokens e transcrição de voz na CPU.
- Orçamento de VRAM e estimativas de latência atualizados em `docs/03-arquitetura.md`.

### Adicionado
- Benchmark do modelo local no hardware real (`docs/benchmarks/2026-10-31-modelo-local.md`).
- Documentação inicial: visão e escopo, requisitos, arquitetura, modelo de dados, segurança, roadmap e guia de desenvolvimento.
- ADRs 0001 a 0009, incluindo a decisão de levar voz e atividades para o MVP (ADR-0009).
- Requisitos de atividades com prazo por voz (RF-34 a RF-40) e meta de precisão de datas (RNF-16).
- Projeto Python com `uv`, layout `src/` e pacotes de cada módulo da arquitetura.
- Configuração validada (`shiro.toml` + variáveis `SHIRO_*`), com padrões seguros e rejeição de chaves desconhecidas.
- Logging estruturado em JSON com rotação e mascaramento de segredos.
- CLI: `shiro --version`, `shiro config path`, `shiro config check`.
- Qualidade: ruff, pyright, import-linter, pytest com cobertura mínima de 80%, pre-commit com gitleaks.
- CI no GitHub Actions (Ubuntu e Windows), verificação de segredos e de vulnerabilidades em dependências, Dependabot.
- `SECURITY.md` e regras para manter dados pessoais fora do repositório público.
- Conjunto inicial de avaliação do agente com 16 casos em pt-BR.
