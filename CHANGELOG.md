# Changelog

Todas as mudanças relevantes do SHIRO são registradas aqui.
Formato baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/) e versionamento [SemVer](https://semver.org/lang/pt-BR/).

## [Não lançado]

### Adicionado
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
