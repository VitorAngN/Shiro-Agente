# Changelog

Todas as mudanças relevantes do SHIRO são registradas aqui.
Formato baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/) e versionamento [SemVer](https://semver.org/lang/pt-BR/).

## [Não lançado]

### Adicionado (marco 1a · agente por texto)
- `shiro chat`: conversa por texto com o agente, confirmação pelo teclado e modo verboso (`-v`).
- Núcleo do agente: `AgentLoop` com limites de passos e tempo, escalonamento para a nuvem respeitando `local_only`, `IntentRouter` com gramática Tier 0 em pt-BR (inclui números por extenso), `EventBus` e verificação de ação alegada.
- `PolicyEngine` com níveis R0–R4, taint por conteúdo externo, confirmação em lote e modo somente leitura.
- Adaptador Ollama com o cliente oficial, aquecimento do prefixo e `num_gpu`.
- Persistência em SQLite: migrações versionadas, histórico de conversas e auditoria append-only com hash encadeado.
- Ferramentas: hora, clima (Open-Meteo), uso do sistema, volume, mídia, abrir e fechar apps da lista permitida. Adaptadores do Windows via Core Audio, teclas de mídia e ShellExecute.
- Configuração: `general.city`, `agent.max_history_messages` e apps com `launch`, `process`, `name` e `aliases`.

### Alterado
- Modelo local carregado inteiro na GPU (`num_gpu = 99`): geração de 13 para 45 tokens/s e latência p50 de 2,1 s para 0,63 s no benchmark (ADR-0011).
- `keep_alive` do modelo local passa para 30 minutos, com aquecimento do prefixo do prompt ao iniciar (ADR-0011).
- Arquitetura ajustada para o hardware real, uma GTX 1650 com 4 GB de VRAM (ADR-0010): modelo local de 3–4B (provisório `qwen3:4b-instruct`), contexto de 4096 tokens e transcrição de voz na CPU.
- Orçamento de VRAM e estimativas de latência atualizados em `docs/03-arquitetura.md`.

### Adicionado
- Benchmark do modelo local no hardware real (`docs/benchmarks/2026-10-31-modelo-local.md`).
- ADR-0011, requisito RF-16 e ameaça A-12: o SHIRO nunca confirma uma ação que nenhuma ferramenta executou.
- Script `evals/bench_ollama.py`: mede velocidade e acerto de ferramentas de um modelo do Ollama com o formato de pedido do SHIRO.
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
