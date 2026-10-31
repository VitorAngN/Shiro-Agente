# ADR-0008 · Processo de usuário iniciado no logon, não serviço do Windows

- **Status:** Aceito
- **Data:** 2026-10-30

## Contexto

O SHIRO precisa estar sempre rodando enquanto eu uso o PC, reiniciar se cair e ter acesso ao microfone, aos alto-falantes, à área de trabalho (janelas, bandeja, notificações) e aos atalhos globais da minha sessão.

Serviços do Windows rodam isolados em uma sessão separada (a "Sessão 0"), sem acesso direto à área de trabalho e aos dispositivos da sessão do usuário.

## Decisão

Rodar o SHIRO como **processo comum do usuário**, sem privilégios de administrador, iniciado no **logon pelo Agendador de Tarefas** do Windows:

- gatilho: logon do usuário, com atraso de ~30 s para não competir com a inicialização do sistema;
- reiniciar automaticamente em caso de falha;
- executar só com o usuário conectado;
- **instância única** garantida por mutex nomeado.

O registro da tarefa é feito por `scripts/register_startup.ps1`, e a remoção pelo mesmo script com `-Uninstall`.

## Alternativas consideradas

| Alternativa | Por que não |
|---|---|
| Serviço do Windows | Isolado da área de trabalho e do áudio da sessão; exigiria um segundo processo na sessão do usuário só para isso |
| Atalho na pasta Inicializar | Simples, mas não reinicia em caso de falha nem permite atraso configurável |
| Rodar como administrador | Desnecessário e perigoso (ameaça A-11) |

## Consequências

- ✅ Acesso natural a áudio, janelas, bandeja e atalhos.
- ✅ Reinício automático sem código próprio de watchdog fora do processo.
- ✅ Privilégio mínimo.
- ⚠️ O SHIRO só roda com o usuário logado. É o comportamento desejado: a casa continua com o Home Assistant (ADR-0006).
