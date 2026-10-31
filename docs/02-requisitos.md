# 02 · Requisitos

Prioridade no formato MoSCoW: **M** (must), **S** (should), **C** (could). A fase indica quando o requisito entra (ver [Roadmap](06-roadmap.md)).

<a id="rf"></a>
## 1. Requisitos funcionais

### 1.1 Interação

| ID | Requisito | Prio. | Fase |
|---|---|---|---|
| RF-01 | Aceitar comandos por texto (CLI e janela rápida) | M | 1 |
| RF-02 | Aceitar comandos por voz com atalho de teclado (push-to-talk) | M | 1 |
| RF-03 | Aceitar comandos por voz com a palavra de ativação "Ei, Shiro" | S | 2 |
| RF-04 | Responder por voz em português e, em paralelo, por notificação do Windows | M | 1 |
| RF-05 | Manter uma janela de continuação de ~5 s após responder, sem exigir nova ativação | S | 2 |
| RF-06 | Permitir interromper a fala do SHIRO (barge-in) por atalho ou nova ativação | S | 2 |
| RF-07 | Ícone na bandeja do sistema mostrando o estado (ocioso, ouvindo, pensando, falando, pausado) | M | 2 |

### 1.2 Agente

| ID | Requisito | Prio. | Fase |
|---|---|---|---|
| RF-10 | Interpretar o pedido e executar uma ou mais ferramentas em sequência | M | 1 |
| RF-11 | Resolver comandos simples conhecidos sem chamar LLM (Tier 0) | M | 1 |
| RF-12 | Escolher o provedor de LLM por regras de roteamento configuráveis | M | 1 |
| RF-13 | Fazer fallback para outro provedor em caso de erro, timeout ou limite de taxa | M | 1 |
| RF-14 | Limitar o número de passos e o tempo de cada turno do agente | M | 1 |
| RF-15 | Manter o contexto da conversa atual (ex.: "e fecha ele também") | M | 1 |

### 1.3 Controle do PC

| ID | Requisito | Prio. | Fase |
|---|---|---|---|
| RF-20 | Abrir, focar e fechar aplicativos de uma lista configurada | M | 1 |
| RF-21 | Ajustar volume geral e silenciar | M | 1 |
| RF-22 | Controlar mídia (tocar, pausar, próxima, anterior) | M | 1 |
| RF-23 | Informar uso de CPU, RAM, GPU, disco e bateria | M | 1 |
| RF-24 | Listar, buscar, mover e renomear arquivos **apenas em pastas permitidas** | S | 3 |
| RF-25 | "Apagar" arquivos movendo para a lixeira própria do SHIRO, com retenção | S | 3 |
| RF-26 | Ativar o Modo Desempenho: descarrega o modelo local e libera a GPU | S | 2 |

### 1.4 Produtividade e informação

| ID | Requisito | Prio. | Fase |
|---|---|---|---|
| RF-30 | Criar, listar e cancelar lembretes e timers que sobrevivem a reinícios | M | 1 |
| RF-31 | Criar rotinas nomeadas compostas por várias ações | S | 3 |
| RF-32 | Pesquisar na web e resumir resultados citando as fontes | S | 3 |
| RF-33 | Informar data, hora e clima | M | 1 |

<a id="atividades"></a>
### 1.5 Atividades

Atividades são tarefas com prazo opcional: trabalhos, entregas, provas, pendências. São diferentes de lembretes: um lembrete é um aviso em um horário; uma atividade é algo a **concluir**, que pode gerar vários avisos.

| ID | Requisito | Prio. | Fase |
|---|---|---|---|
| RF-34 | Criar atividade por voz ou texto com título, contexto opcional (disciplina, projeto) e prazo em linguagem natural ("pra sexta", "dia 12 às 23h59", "semana que vem") | M | 1 |
| RF-35 | Repetir em voz alta o que entendeu, com data absoluta, antes de salvar ("Anotado: trabalho de cálculo, sexta, 6 de novembro, 23h59") | M | 1 |
| RF-36 | Listar atividades por período, contexto ou status ("o que eu tenho essa semana?", "quais estão atrasadas?") | M | 1 |
| RF-37 | Concluir, adiar, editar e excluir atividades por voz | M | 1 |
| RF-38 | Avisar antes do prazo, por voz e notificação (padrão: 1 dia antes e 2 h antes, configurável) | M | 1 |
| RF-39 | Resumo das atividades do dia ao iniciar o PC ou sob pedido | S | 2 |
| RF-40 | Sincronizar atividades com um calendário ou app de tarefas externo | C | futuro |

### 1.6 Memória

| ID | Requisito | Prio. | Fase |
|---|---|---|---|
| RF-41 | Guardar fatos e preferências quando eu pedir explicitamente ("lembra que…") | S | 3 |
| RF-42 | Recuperar memórias relevantes por similaridade e usá-las no contexto | S | 3 |
| RF-43 | Esquecer um fato ou tudo sob comando ("esquece isso") | S | 3 |
| RF-44 | Listar o que está guardado | S | 3 |

### 1.7 Casa (futuro)

| ID | Requisito | Prio. | Fase |
|---|---|---|---|
| RF-50 | Consultar e controlar dispositivos via Home Assistant | C | 5 |
| RF-51 | Usar dispositivos da casa dentro de rotinas | C | 5 |

### 1.8 Administração

| ID | Requisito | Prio. | Fase |
|---|---|---|---|
| RF-60 | Parada de emergência por atalho global: cancela ações e desliga o microfone | M | 1 |
| RF-61 | Iniciar automaticamente com o login no Windows | M | 2 |
| RF-62 | Registrar trilha de auditoria de toda chamada de ferramenta | M | 1 |
| RF-63 | Painel local com histórico, auditoria, custos e métricas | C | 4 |
| RF-64 | Configuração por arquivo `shiro.toml`, com segredos fora do arquivo | M | 0 |

<a id="rnf"></a>
## 2. Requisitos não funcionais

As metas de desempenho são hipóteses iniciais. Elas serão medidas no spike da Fase 1 e revisadas com dados reais.

| ID | Categoria | Requisito | Meta |
|---|---|---|---|
| RNF-01 | Desempenho | Latência do fim da fala até o início da resposta falada (p50) | Tier 0 ≤ 1,0 s · Tier 1 ≤ 2,5 s · Tier 2 ≤ 5,0 s |
| RNF-02 | Desempenho | Consumo ocioso (só escutando a palavra de ativação) | CPU < 5% · VRAM do LLM liberada após inatividade configurável |
| RNF-03 | Precisão | Acerto de chamada de ferramenta na suíte de avaliação | ≥ 90% no modelo padrão |
| RNF-04 | Precisão | Palavra de ativação | Recall ≥ 90% · ≤ 1 falso disparo por dia de uso normal |
| RNF-05 | Privacidade | Áudio processado só localmente; nada gravado em disco por padrão | 0 bytes de áudio enviados à rede |
| RNF-06 | Privacidade | Dados marcados como `local_only` nunca vão para a nuvem | Verificado por teste automatizado do roteador |
| RNF-07 | Segurança | Ações R3 sempre com confirmação física | 100% na auditoria |
| RNF-08 | Disponibilidade | Recuperação automática após falha de componente | Reinício do componente em < 5 s sem derrubar o processo |
| RNF-09 | Offline | Tier 0 e Tier 1 funcionam sem internet | Suíte offline passando |
| RNF-10 | Custo | Orçamento diário de nuvem configurável, com bloqueio ao atingir | Nenhum gasto acima do orçamento |
| RNF-11 | Manutenibilidade | Cobertura de testes do núcleo (`core`, `policy`, `llm`) | ≥ 80% |
| RNF-12 | Manutenibilidade | Tipagem estática estrita | `pyright --strict` sem erros no núcleo |
| RNF-13 | Extensibilidade | Adicionar ferramenta sem alterar o núcleo | 1 arquivo + testes |
| RNF-14 | Observabilidade | Logs estruturados e métricas por estágio | Todo turno tem `trace_id` ponta a ponta |
| RNF-15 | Portabilidade | Núcleo sem dependência de Windows | Testes do núcleo rodam também em Linux na CI |
| RNF-16 | Precisão | Interpretação de prazos em linguagem natural pt-BR | ≥ 95% de datas corretas na suíte de avaliação |

## 3. Rastreabilidade

| Objetivo | Requisitos |
|---|---|
| OBJ-1 Resposta rápida | RF-11, RNF-01, RNF-02 |
| OBJ-2 Offline | RF-11, RF-12, RNF-09 |
| OBJ-3 Segurança | RF-60, RF-62, RNF-07 |
| OBJ-4 Agnóstico de modelo | RF-12, RF-13 |
| OBJ-5 Extensível | RNF-13 |
| OBJ-6 Portfólio | RNF-11, RNF-12, RNF-14, RNF-15 |
| OBJ-7 Atividades por voz | RF-02, RF-34 a RF-38, RNF-16 |
