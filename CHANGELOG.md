# Changelog

Todas as mudanças relevantes do SHIRO são registradas aqui.
Formato baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/) e versionamento [SemVer](https://semver.org/lang/pt-BR/).

## [Não lançado]

### Adicionado (Fase 4 · painel)
- Painel local em `127.0.0.1` (ADR-0019), aberto pela bandeja ("Abrir painel") ou por `shiro dashboard`:
  - turnos com camada, tempo, ferramentas e a decisão da política, p50/p95 por camada e ações barradas;
  - atividades pendentes, memórias (com "Esquecer"), rotinas, auditoria com verificação da cadeia e custos da nuvem;
  - eventos ao vivo por WebSocket quando roda junto da bandeja.
- Segurança do serviço local: link de entrada de uso único, cookie `HttpOnly`/`SameSite=Strict`, `Host` e `Origin` conferidos, `X-Shiro` para apagar, CSP sem nada inline nem externo, porta exclusiva no Windows.
- Fontes da identidade (Chakra Petch, JetBrains Mono, Noto Sans JP só para 白シロ) embutidas em subconjuntos, com a licença OFL.

### Adicionado (Fase 3 · rotinas, arquivos e web)
- Rotinas nomeadas ("modo estudo") no `shiro.toml`, validadas na partida, executadas no Tier 0 com cada passo pela política (ADR-0018).
- Arquivos nas pastas permitidas (padrão: Downloads): listar, procurar, mover, renomear, mandar para a lixeira da SHIRO, restaurar e organizar por tipo, com o plano na confirmação.
- Pesquisa na web com fontes pelo Gemini (grounding), nos limites e orçamento do Tier 2.
- Ferramentas por assunto: memória, arquivos e web só aparecem para o modelo quando o pedido é do assunto ou o grupo foi usado há pouco.
- Política: `confirm` (sempre confirma) e `external` (manda dados para fora; pede confirmação em turno com dados pessoais).

### Adicionado (Fase 3 · memória)
- Memória de longo prazo (ADR-0017):
  - "lembra que…", "esquece…", "esquece tudo", "o que você sabe sobre mim?";
  - busca por semelhança com `paraphrase-multilingual-MiniLM-L12-v2` em ONNX na CPU (10/10 no fato certo na calibração), com reserva por radicais sem download;
  - recusa senhas, documentos e dados bancários;
  - as memórias relevantes entram no contexto só do modelo local, e o turno não sobe para a nuvem.
- `shiro setup`: baixa e prepara ouvido, voz e memória de uma vez.

### Adicionado (Fase 2 · sempre ligado)
- Bandeja do Windows (`shiro tray` / `shiro-tray` sem console):
  - ícone por estado na paleta da SHIRO;
  - menu para falar, parar, "Ei, Shiro", liberar a GPU, iniciar com o Windows, registros e sair;
  - lembretes e resumo do dia como notificação (ADR-0016).
- "Ei, Shiro":
  - motor `whisper`: VAD e um Whisper rápido conferem o nome, sem treino; entende "Ei Shiro, abre o Spotify" de uma vez;
  - motor `openwakeword`: em ONNX puro, com modelos fixados por SHA-256 e guia de treino.
- Janela de continuação: depois de responder, ela ouve por mais 5 s sem precisar chamar de novo.
- Instância única (mutex `Local\SHIRO-Agente`) para voz e bandeja.
- `shiro autostart on|off|status`: tarefa no Agendador (logon + 30 s, sem admin, reinício em falha), com reserva na chave `Run`.
- Confirmação física na bandeja por janela "Sim/Não" (padrão "Não").
- `shiro voice bench --wake`: mede a palavra de ativação sem tocar áudio.

### Adicionado (marco 1b · voz)
- `shiro voice`: conversa por voz com atalho global (`ctrl+alt+space`) ou Enter, atalho de parar (`ctrl+alt+shift+s`) e texto digitado no mesmo terminal (ADR-0015).
- Detecção de fala com o Silero VAD v6 do faster-whisper, quadro a quadro, com histerese e pré-escuta. Um segundo toque no atalho encerra a frase.
- Transcrição com faster-whisper na CPU (int8), com prompt de vocabulário ("Shiro", apps) e descarte de alucinações conhecidas.
- Voz Kokoro `pf_dora` num processo separado, sintetizada frase a frase enquanto a anterior toca. Reserva: voz Maria do Windows (SAPI). Antes da síntese o texto é ajustado ("23h59" → "23 e 59").
- Confirmação por voz ("sim"/"não"; sem resposta = não). A confirmação física continua no teclado.
- Lembretes e avisos de prazo falados.
- `shiro voice setup | devices | say | listen | bench`. O `bench` mede voz e transcrição sem tocar áudio.

### Adicionado (marco 1c · atividades)
- Resolução determinística de prazos em pt-BR (`shiro.activities.dates`): dias da semana, "que vem", "dia 12 às 19h", "12/11", "daqui a 3 dias", "às oito da noite", meio-dia e meia-noite. Expressões vagas viram pergunta, nunca chute.
- Atividades: criar, listar por período, concluir, adiar (mantendo o horário), renomear e excluir; a SHIRO repete a data absoluta entendida. Lembretes com horário.
- Migração 0002 com `activity` e `scheduled_job`; agendador que dispara avisos antes do prazo (padrão: 1 dia e 2 horas) e lembretes, inclusive os que venceram com o PC desligado.
- Tier 0: "terminei X", "marca X como feita", "o que eu tenho essa semana/amanhã/hoje?", "o que tá atrasado?".
- Avisos no terminal do `shiro chat`.
- Prazos ancorados na fala do usuário (ADR-0014): se o modelo corta ou parafraseia o prazo ("às 8h" para "amanhã às 8h"), vale o que o usuário disse.
- Tier 0 para criar atividades e lembretes nas frases comuns: "tenho prova de física dia 12 às 19h", "tenho que entregar o relatório sexta", "anota que eu preciso comprar café", "me lembra de X às seis". Também "já dei conta de X", "já fiz X", "X já era / tá pronto", "risca X" e "dá baixa em X" para concluir.
- Dia e hora separados na frase ("amanhã tenho prova às 10") contam como um prazo só.
- Prazos: "às seis" vira o próximo seis do relógio (6h ou 18h); "daqui a 40 minutos", "em 2 horas"; "de manhã", "à tarde", "à noite".
- Avaliação: relógio fixo, prazos comparados pelo momento que produzem e tokens do pedido por caso.

### Corrigido (marco 1c)
- A checagem de ação alegada deixava passar "Chamei a ferramenta para marcar…" e promessas como "Vou marcar como concluída" sem ferramenta chamada.
- O schema compacto das ferramentas apagava o campo `title` (confundido com o metadado `title` do JSON Schema); o modelo recebia o campo como obrigatório sem definição e omitia o título.
- "estudar 2 horas" não é mais lido como horário.
- `evals/run_agent.py` não quebra mais com saída redirecionada no Windows (cp1252).

### Adicionado (marco 1a concluído)
- Tier 2 com Gemini pelo SDK oficial (`google-genai`): conversão de mensagens e ferramentas, assinaturas de pensamento preservadas entre passos, chamada automática de funções desligada.
- Proteções da nuvem: limite por minuto, limite diário de pedidos, orçamento diário estimado (`provider_usage`) e cadeia de fallback. Se a nuvem falha ou passa do limite, a SHIRO volta para o modelo local.
- `shiro secrets set|status|delete`: chaves de API no Gerenciador de Credenciais do Windows (`keyring`); a chave nunca aparece na tela nem em logs.
- `evals/run_agent.py`: avaliação do agente completo (Tier 0, modelo, política e ferramentas) com o PC simulado.
- `AgentLoop.reset()` para começar uma conversa nova.

### Adicionado (identidade e localização)
- Identidade da SHIRO (ADR-0012): persona feminina de tom neutro com gíria de netrunner rara, voz feminina pt-BR (Kokoro `pf_dora` como candidata), paleta e esboço conceitual em `docs/assets/shiro-conceito.svg`. Documento `docs/08-identidade.md`.
- Visual cyberpunk no `shiro chat`: banner, prompts `você ▸` / `shiro ▸`, cores da paleta e checagens de inicialização (modelo, auditoria, modo somente leitura). Respeita `NO_COLOR`.
- Detecção automática da cidade para o clima pelo IP, com cache local de 24 h e opção `general.location = "off"` (ADR-0013).
- Perguntas de clima no Tier 0 ("como tá o tempo?", "vai chover hoje?").

### Alterado (identidade e localização)
- A ferramenta de clima passa a ser `local_only`, porque revela a localização.
- `voice.tts` passa a ter `engine = "kokoro"`, `voice = "pf_dora"` e `speed`, no lugar de `length_scale`.

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
