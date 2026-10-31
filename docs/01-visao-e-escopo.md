# 01 · Visão e escopo

| Campo | Valor |
|---|---|
| Projeto | SHIRO |
| Versão do documento | 0.1 |
| Data | 2026-10-30 |
| Autor | Vitor (@VitorAngN) |
| Status | Rascunho aprovado para a Fase 0 |

## 1. Problema

Tarefas pequenas e repetitivas no PC consomem atenção: abrir os mesmos programas para estudar, ajustar volume, achar um arquivo, lembrar de uma entrega, organizar a pasta Downloads. Anotar atividades e prazos também exige parar o que se está fazendo para abrir outro app. Assistentes comerciais (Alexa, Google Assistente, Copilot) não controlam o PC de forma profunda, não são extensíveis do jeito que eu quero e mandam tudo para a nuvem.

## 2. Visão

> Um assistente pessoal que entende linguagem natural em português, age no meu PC (e futuramente na casa) com segurança, roda localmente sempre que possível e cresce por meio de ferramentas plugáveis.

## 3. Objetivos

| ID | Objetivo | Como medir |
|---|---|---|
| OBJ-1 | Executar comandos de voz do dia a dia com resposta rápida | Latência p50 dentro das metas de [RNF-01](02-requisitos.md#rnf) |
| OBJ-2 | Funcionar offline para comandos comuns | Suíte de avaliação passa sem internet nos comandos Tier 0 e Tier 1 |
| OBJ-3 | Nunca executar ação irreversível sem confirmação | 100% das ações R3 com confirmação registrada na auditoria |
| OBJ-4 | Trocar de modelo de IA sem alterar código | Troca feita só pelo `shiro.toml` |
| OBJ-5 | Ser extensível | Ferramenta nova = um arquivo + testes, sem tocar no núcleo |
| OBJ-6 | Servir como projeto de portfólio de nível profissional | Documentação, ADRs, CI, cobertura e métricas públicas no repositório |
| OBJ-7 | Registrar e consultar atividades por voz sem parar o que estou fazendo | Atividade criada com uma única frase, com a data confirmada em voz alta ([RF-34 a RF-38](02-requisitos.md#atividades)) |

## 4. Não-objetivos (fora de escopo, por enquanto)

- Treinar ou fazer fine-tuning de um LLM próprio.
- Suportar vários usuários ou vários PCs.
- Rodar em macOS ou Linux. O núcleo é portável, mas os adaptadores de sistema são só para Windows.
- Agir em sites logados, fazer compras ou movimentar dinheiro.
- Executar comandos arbitrários de terminal escolhidos pelo modelo.
- Disponibilizar o SHIRO como produto para terceiros.

## 5. Usuário

Um único usuário: o dono do PC. Usa o computador para estudo, desenvolvimento e lazer, fala português do Brasil e prefere respostas curtas e diretas.

A assistente tem identidade própria: **a SHIRO** (白, "branco"), com persona feminina, tom neutro e estética cyberpunk. Ver [08 · Identidade](08-identidade.md).

## 6. Casos de uso principais

| ID | Caso de uso | Exemplo de fala | Prioridade |
|---|---|---|---|
| UC-01 | Abrir e fechar aplicativos | "Abre o VS Code e o Spotify" | Must |
| UC-02 | Controlar áudio e mídia | "Volume em 30", "pula essa música" | Must |
| UC-03 | Perguntar coisas gerais | "Quanto é 15% de 340?", "o que é transformada de Fourier?" | Must |
| UC-04 | Informações do sistema | "Quanto de RAM estou usando?" | Must |
| UC-05 | Lembretes e timers | "Me lembra de entregar o relatório de Física às 20h" | Must |
| UC-06 | Rotinas | "Modo estudo" abre os apps, silencia notificações e liga um timer | Should |
| UC-07 | Organizar arquivos em pastas permitidas | "Organiza meus Downloads por tipo" | Should |
| UC-08 | Pesquisar na web e resumir | "Pesquisa as novidades do Python 3.14" | Should |
| UC-09 | Memória de preferências | "Lembra que eu estudo melhor com lo-fi" | Should |
| UC-10 | Controlar a casa | "Apaga a luz do quarto" | Could (Fase 5) |
| UC-11 | Painel de controle | Ver histórico, custos e auditoria no navegador | Could |
| UC-12 | Parada de emergência | Atalho que interrompe tudo e desliga o microfone | Must |
| UC-13 | Registrar e consultar atividades por voz | "Anota o trabalho de cálculo pra sexta", "o que eu tenho essa semana?" | Must |

## 7. Restrições

| Tipo | Restrição |
|---|---|
| Hardware | PC com Windows e GPU NVIDIA GTX 1650 com 4 GB de VRAM, compartilhada com o uso normal do PC ([ADR-0010](adr/0010-hardware-gpu-4gb.md)) |
| Custo | Nuvem usada de forma econômica; plano gratuito do Gemini no início, com limites baixos |
| Tempo | Projeto pessoal, desenvolvido em paralelo à faculdade; entregas em fases pequenas |
| Privacidade | Áudio e arquivos pessoais não saem do PC sem autorização explícita |

## 8. Premissas e riscos

| Risco | Probabilidade | Impacto | Resposta |
|---|---|---|---|
| Modelo local de 3–4B erra chamadas de ferramenta em pt-BR | Alta | Alto | Benchmark próprio no marco 1a; Tier 0 amplo; escalonar para a nuvem quando a validação falhar |
| Transcrição na CPU lenta demais | Média | Médio | Spike no marco 1b compara os modelos `base` e `small`; STT já sai da GPU por decisão do ADR-0010 |
| Palavra de ativação com muitos falsos disparos | Alta | Médio | Começar com atalho de teclado; wake word só na Fase 2, com metas medidas |
| Limites do plano gratuito na nuvem | Alta | Baixo | Roteador com limitador de taxa e fallback local |
| Escopo crescer demais | Alta | Alto | Roadmap com critérios de pronto; nada entra sem ADR ou item no roadmap |
